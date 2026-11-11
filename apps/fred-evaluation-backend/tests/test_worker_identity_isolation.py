"""Worker identity isolation (EVAL-AUTH RFC — issue #33, part 2).

Proves the invariants that must hold on the asynchronous side:
- the Temporal payload (`RunInput`) carries only `run_id` — never a
  bearer token;
- the persisted run row carries `created_by` + `team_id` (the legitimacy
  anchor) but no credential column;
- both worker engines use the frozen URL and send only M2M credentials plus
  the creator/run/instance assertion, without another preparation call.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast, override

import httpx
import pytest
from fred_core import M2MAuthConfig, M2MTokenProvider
from fred_pod.security.backend_to_backend_auth import TokenLease
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import create_async_engine

from fred_evaluation_backend.config.models import EvaluationConfig
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.outbound_auth import UserAuthentication
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.base import Base
from fred_evaluation_backend.runs.models import EvaluationRunRow
from fred_evaluation_backend.runs.schemas import ManagedInstanceTarget
from fred_evaluation_backend.runs.store import RunStore
from fred_evaluation_backend.workers import _activity_context
from fred_evaluation_backend.workers.runner import RunRunner
from fred_evaluation_backend.workers.workflow import (
    RunCaseInput,
    RunInput,
    run_case_for_run,
)

Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)


class _SpyM2MProvider(M2MTokenProvider):
    def __init__(self) -> None:
        super().__init__(
            M2MAuthConfig(
                keycloak_realm_url="http://keycloak.test/realms/test",
                client_id="spy-worker-client",
                secret_env="SPY_M2M_SECRET_ENV_UNUSED",
            )
        )
        self.calls = 0

    async def get_token(self) -> str:
        self.calls += 1
        return "worker-m2m-token"

    @override
    async def get_token_lease(self) -> TokenLease:
        # M2MBearerAuth authenticates through a lease, not get_token().
        return TokenLease(await self.get_token(), 0)


def _patch_transport(monkeypatch: MonkeyPatch, handler: Handler) -> None:
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(**kwargs) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_run_input_carries_no_credential():
    """The Temporal workflow payload must never widen to carry a credential.

    Kept as a closed allowlist rather than a substring check alone: any new field
    has to be added here deliberately, which is the point — the guard should make
    someone stop and think, even when the addition is innocuous.

    `max_concurrency` is such a case: it is pacing data that must live in the event
    history so a replay on another worker behaves identically, not an identity.
    """
    fields = {f.name for f in dataclasses.fields(RunInput)}
    assert fields == {"run_id", "max_concurrency"}

    forbidden_substrings = (
        "token",
        "bearer",
        "authorization",
        "credential",
        "secret",
        "password",
        "auth",
    )
    for field in fields:
        lowered = field.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), (
            f"RunInput.{field} looks like a credential"
        )


def test_run_row_has_the_legitimacy_anchor_but_no_credential_column():
    columns = {c.name for c in EvaluationRunRow.__table__.columns}
    assert {"created_by", "team_id"} <= columns

    forbidden_substrings = (
        "token",
        "bearer",
        "authorization",
        "credential",
        "secret",
        "password",
    )
    for column in columns:
        lowered = column.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), (
            f"run row column {column!r} looks like a stored credential"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("worker", ["temporal", "polling"])
async def test_workers_use_frozen_url_and_m2m_delegation(
    monkeypatch: MonkeyPatch, tmp_path: Path, worker: str
) -> None:
    seen: list[httpx.Request] = []
    space_id = "11111111-1111-1111-1111-111111111111"
    instance_id = "22222222-2222-2222-2222-222222222222"
    evaluate_url = "http://runtime.test/pod/agents/evaluate"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "cp.test":
            assert request.headers["authorization"] == "Bearer api-caller-token"
            if request.url.path == "/authorize/space":
                assert json.loads(request.content) == {
                    "space_id": space_id,
                    "permission": "run_evaluations",
                }
                return httpx.Response(200, json={"allowed": True})
            assert (
                request.url.path
                == f"/spaces/{space_id}/agent-instances/{instance_id}/prepare-execution"
            )
            assert not request.url.query
            return httpx.Response(
                200,
                json={
                    "execute_url": "/pod/agents/execute",
                    "runtime_id": "rt-1",
                    "space_id": space_id,
                    "agent_instance_id": instance_id,
                },
            )
        assert str(request.url.copy_with(query=None)) == evaluate_url
        assert request.headers["authorization"] == "Bearer worker-m2m-token"
        body = cast(dict[str, object], json.loads(request.content))
        assert body == {
            "agent_instance_id": instance_id,
            "input": "q1",
            "runtime_context": {
                "space_id": space_id,
                "team_id": space_id,
                "user_id": "alice",
            },
        }
        assert dict(request.url.params) == {
            "person": "alice",
            "run": result.run_id,
            "agent": instance_id,
        }
        return httpx.Response(
            200,
            json={
                "session_id": "pod-generated",
                "agent_id": "agent-1",
                "input": "q1",
                "output": "answer",
                "latency_ms": 10,
            },
        )

    _patch_transport(monkeypatch, handler)
    spy = _SpyM2MProvider()
    cp_client = ControlPlaneClient(
        base_url="http://cp.test",
        runtime_base_url="http://runtime.test",
        m2m_token_provider=spy,
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        store = RunStore(engine)
        evaluations = EvaluationStore(engine)
        _ = await evaluations.create_evaluation(
            evaluation_id="eval-1",
            name="golden",
            version="v1",
            team_id=space_id,
            created_by="alice",
            origin="manual",
            completeness="minimal",
            cases_json='[{"input":"q1"}]',
        )
        result = await service.start_run(
            evaluation_id="eval-1",
            team_id=space_id,
            target=ManagedInstanceTarget(
                kind="managed_instance", agent_instance_id=instance_id
            ),
            created_by="alice",
            store=store,
            evaluation_store=evaluations,
            control_plane_client=cp_client,
            auth=UserAuthentication(authorization_header="Bearer api-caller-token"),
            profile="auto",
            judge_profile_id="none",
            agent_model_override=None,
            max_concurrency=1,
            metrics=["answer_relevancy"],
            custom_metrics=[],
        )
        row = await store.get_run(result.run_id)
        assert row is not None
        assert json.loads(row.snapshot_json)["evaluate_url"] == evaluate_url
        assert "api-caller-token" not in row.snapshot_json
        assert spy.calls == 0
        config = cast(
            EvaluationConfig,
            cast(
                object,
                SimpleNamespace(
                    worker=SimpleNamespace(judge_profiles={}, max_concurrent_cases=1)
                ),
            ),
        )
        if worker == "temporal":
            _activity_context.init(
                store=store,
                config=config,
                agent_client=AgentClient(),
                cp_client=cp_client,
            )
            cases = await store.list_cases_by_run(result.run_id)
            await run_case_for_run(
                RunCaseInput(case_id=cases[0].case_id, run_id=result.run_id)
            )
        else:
            runner = RunRunner(config=config, engine=engine, cp_client=cp_client)
            await runner._execute_run(row)  # pyright: ignore[reportPrivateUsage]
        cases = await store.list_cases_by_run(result.run_id)
        assert cases[0].status == "completed", cases[0].execution_error
        assert len(seen) == 3  # authorize + prepare on the API, evaluate on the worker
        assert spy.calls == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_evaluation_without_m2m_fails_before_http(
    monkeypatch: MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("No fallback token or unauthenticated request is allowed")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="M2M token provider"):
        _ = await AgentClient().evaluate(
            evaluate_url="http://runtime.test/agents/evaluate",
            team_id="space-1",
            agent_instance_id="inst-1",
            created_by="alice",
            run_id="run-1",
            input="q1",
        )
