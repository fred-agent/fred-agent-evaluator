"""Worker identity isolation (EVAL-AUTH RFC — issue #33, part 2).

Proves the invariants that must hold on the asynchronous side:
- the Temporal payload (`RunInput`) carries only `run_id` — never a
  bearer token;
- the persisted run row carries `created_by` + `team_id` (the legitimacy
  anchor) but no credential column;
- the Temporal activity (`run_case_for_run`) resolves the Control Plane using the
  worker's own M2M service identity, never a user token — proven by actually
  running the activity function against a real `ControlPlaneClient` wired to
  an `httpx.MockTransport`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Callable, cast

import httpx
import pytest
from fred_core import M2MAuthConfig, M2MTokenProvider
from pytest import MonkeyPatch

from fred_evaluation_backend.config.models import EvaluationConfig
from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.outbound_auth import UserAuthentication
from fred_evaluation_backend.runs.models import EvaluationRunRow
from fred_evaluation_backend.runs.store import RunStore
from fred_evaluation_backend.workers import _activity_context
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


class _FakeStore:
    """Duck-typed RunStore stand-in — only the methods run_case_for_run calls."""

    def __init__(self) -> None:
        # Recorded so tests can assert the incremental-progress refresh
        # (added alongside the worker-identity fix) actually ran.
        self.aggregate_updates: list[dict[str, object]] = []

    async def get_run(self, run_id: str) -> object:
        return SimpleNamespace(
            run_id=run_id,
            evaluation_id="eval-1",
            team_id="team-1",
            target_instance_id="inst-1",
            judge_profile_id="none-configured",
            custom_metrics_json=None,
            metrics_json=None,
            created_by="alice",
            profile="auto",
            target_agent_id=None,
        )

    async def get_case(self, case_id: str) -> object:
        return SimpleNamespace(case_id=case_id, input="q1", expected_output=None)

    async def list_cases_by_run(self, run_id: str, limit: int = 10000) -> list[object]:
        # execute_and_score_case is faked out in these tests, so no real case
        # rows exist to read back — an empty list is enough for
        # run_case_for_run's post-case aggregate refresh to run harmlessly.
        return []

    async def update_run_aggregates(self, run_id: str, **kwargs: object) -> None:
        self.aggregate_updates.append({"run_id": run_id, **kwargs})


@pytest.mark.asyncio
async def test_run_case_for_run_activity_resolves_control_plane_with_worker_m2m_identity(
    monkeypatch: MonkeyPatch,
) -> None:
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={
                "execute_url": "/agents/execute",
                "runtime_id": "rt-1",
                "team_id": "team-1",
            },
        )

    _patch_transport(monkeypatch, handler)

    spy = _SpyM2MProvider()
    cp_client = ControlPlaneClient(base_url="http://cp.test", m2m_token_provider=spy)

    recorded_calls: list[dict[str, object]] = []

    async def fake_execute_and_score_case(**kwargs: object) -> None:
        recorded_calls.append(kwargs)

    monkeypatch.setattr(
        "fred_evaluation_backend.workers.activities.execute_and_score_case",
        fake_execute_and_score_case,
    )

    # Test doubles satisfy the runtime interface run_case actually uses; cast
    # tells the type checker to trust that (RunStore/EvaluationConfig/
    # AgentClient are concrete classes, not Protocols, so structural fakes need it).
    _activity_context.init(
        store=cast(RunStore, cast(object, _FakeStore())),
        config=cast(
            EvaluationConfig,
            cast(
                object,
                SimpleNamespace(
                    worker=SimpleNamespace(judge_profiles={}, max_concurrent_cases=1)
                ),
            ),
        ),
        agent_client=cast(AgentClient, cast(object, SimpleNamespace())),
        cp_client=cp_client,
    )

    await run_case_for_run(RunCaseInput(case_id="case-1", run_id="run-1"))

    # The Control Plane call used the worker's M2M identity, not a user token.
    assert seen_auth_headers == ["Bearer worker-m2m-token"]
    assert spy.calls == 1

    # No bearer/authorization value was smuggled into the scoring call either.
    assert len(recorded_calls) == 1
    assert "authorization" not in {str(k).lower() for k in recorded_calls[0]}
    assert recorded_calls[0]["token_provider"] is spy


@pytest.mark.asyncio
async def test_worker_resolution_cannot_reuse_a_prior_api_caller_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """Even on the same client instance, a prior interactive call's bearer token
    must never resurface on a later worker (M2M) call."""
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={
                "execute_url": "/agents/execute",
                "runtime_id": "rt-1",
                "team_id": "team-1",
            },
        )

    _patch_transport(monkeypatch, handler)

    spy = _SpyM2MProvider()
    cp_client = ControlPlaneClient(base_url="http://cp.test", m2m_token_provider=spy)

    # Simulate a prior interactive (API) call on this same client instance.
    await cp_client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=UserAuthentication(authorization_header="Bearer api-caller-token"),
    )

    async def fake_execute_and_score_case(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "fred_evaluation_backend.workers.activities.execute_and_score_case",
        fake_execute_and_score_case,
    )
    _activity_context.init(
        store=cast(RunStore, cast(object, _FakeStore())),
        config=cast(
            EvaluationConfig,
            cast(
                object,
                SimpleNamespace(
                    worker=SimpleNamespace(judge_profiles={}, max_concurrent_cases=1)
                ),
            ),
        ),
        agent_client=cast(AgentClient, cast(object, SimpleNamespace())),
        cp_client=cp_client,
    )

    # The worker's own resolution — must use M2M, never the prior caller's token.
    await run_case_for_run(RunCaseInput(case_id="case-1", run_id="run-1"))

    assert seen_auth_headers == ["Bearer api-caller-token", "Bearer worker-m2m-token"]
