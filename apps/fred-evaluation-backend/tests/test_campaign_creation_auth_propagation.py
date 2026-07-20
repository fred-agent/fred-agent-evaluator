"""POST /evaluations/{evaluation_id}/runs identity propagation (EVAL-AUTH RFC — issue #33, parts 1+2).

Drives the real FastAPI route (`campaigns/api.py` -> `campaigns/service.py` ->
`execution/runtime_resolver.py`) end-to-end over an in-process ASGI transport
(no sockets, no DB, no Temporal). The Control Plane client is faked so we can
record exactly which `OutboundAuth` value reaches it — the thing this issue is
about — without needing a live Control Plane.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fred_core import KeycloakUser, get_config, get_current_user

from fred_evaluation_backend.runs.api import (
    _get_control_plane_client,
    _get_evaluation_catalog_store,
    _get_run_store,
    build_evaluations_router,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    normalize_unstructured_auth_error,
)
from fred_evaluation_backend.execution.outbound_auth import (
    NoAuthentication,
    ServiceAuthentication,
    UserAuthentication,
)

EVALUATION_ID = "eval-1"

RUN_BODY = {
    "team_id": "team-1",
    "target": {"kind": "managed_instance", "agent_instance_id": "inst-1"},
}


def _evaluation_row(*, evaluation_id: str = EVALUATION_ID, team_id: str = "team-1"):
    return SimpleNamespace(
        evaluation_id=evaluation_id,
        name="ds1",
        version="v1",
        team_id=team_id,
        origin="manual",
        completeness="minimal",
        cases_json=json.dumps([{"input": "q1"}]),
    )


class _FakeStore:
    def __init__(self) -> None:
        self.created_cases: list[dict[str, object]] = []

    async def create_run(self, **kwargs):
        return None

    async def create_case(self, **kwargs):
        self.created_cases.append(kwargs)
        return None


class _FakeEvaluationStore:
    """Serves one evaluation (`EVALUATION_ID`, team `team-1`) — 404s everything else."""

    def __init__(self, *, rows: dict[str, object] | None = None) -> None:
        self._rows = rows if rows is not None else {EVALUATION_ID: _evaluation_row()}

    async def get_evaluation(self, evaluation_id: str):
        return self._rows.get(evaluation_id)


class _RecordingControlPlaneClient:
    """Fake ControlPlaneClient: records the OutboundAuth each call received."""

    def __init__(self) -> None:
        self.received_auths: list[object] = []

    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth
    ):
        self.received_auths.append(auth)
        return SimpleNamespace(
            agent_instance_id=agent_instance_id,
            runtime_id="rt-1",
            team_id=team_id,
            evaluate_url="http://runtime.test/agents/evaluate",
        )

    async def prepare_runtime_agent_execution(
        self, *, team_id, runtime_id, agent_id, auth
    ):
        self.received_auths.append(auth)
        return SimpleNamespace(
            runtime_id=runtime_id,
            agent_id=agent_id,
            team_id=team_id,
            evaluate_url="http://runtime.test/agents/evaluate",
        )


class _ForbiddenControlPlaneClient:
    """Fake ControlPlaneClient whose prepare_* calls always raise an upstream 403.

    Raises the real `httpx.HTTPStatusError` `resolve_managed_instance` classifies,
    so the response below is produced by the real resolver + error mapping, not
    by a hand-written test assertion.
    """

    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth
    ):
        request = httpx.Request("POST", "http://cp.test/prepare-execution")
        response = httpx.Response(403, request=request, json={"detail": "forbidden"})
        raise httpx.HTTPStatusError("403 Forbidden", request=request, response=response)

    async def prepare_runtime_agent_execution(
        self, *, team_id, runtime_id, agent_id, auth
    ):
        raise NotImplementedError


def _build_app(
    *,
    security_enabled: bool,
    cp_client: _RecordingControlPlaneClient | _ForbiddenControlPlaneClient,
    store: _FakeStore | None = None,
    evaluation_store: _FakeEvaluationStore | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(build_evaluations_router())
    # Mirrors main.py's create_app() wiring — proves a real Control Plane 403
    # (already-structured) passes through this handler unchanged.
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_current_user] = lambda: KeycloakUser(
        uid="alice", username="alice", roles=[], email="alice@test.example"
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=security_enabled)),
        worker=SimpleNamespace(judge_profiles={}),
    )
    app.dependency_overrides[_get_run_store] = lambda: store or _FakeStore()
    app.dependency_overrides[_get_evaluation_catalog_store] = lambda: (
        evaluation_store or _FakeEvaluationStore()
    )
    app.dependency_overrides[_get_control_plane_client] = lambda: cp_client
    return app


@pytest.mark.asyncio
async def test_start_run_propagates_the_caller_authorization_header():
    cp_client = _RecordingControlPlaneClient()
    app = _build_app(security_enabled=True, cp_client=cp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 202
    assert len(cp_client.received_auths) == 1
    auth = cp_client.received_auths[0]
    assert isinstance(auth, UserAuthentication)
    assert auth.authorization_header == "Bearer alice-token"


@pytest.mark.asyncio
async def test_start_run_never_uses_service_authentication_interactively():
    cp_client = _RecordingControlPlaneClient()
    app = _build_app(security_enabled=True, cp_client=cp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 202
    assert not any(
        isinstance(a, ServiceAuthentication) for a in cp_client.received_auths
    )


@pytest.mark.asyncio
async def test_start_run_dev_mode_security_disabled_is_explicit_not_m2m():
    cp_client = _RecordingControlPlaneClient()
    app = _build_app(security_enabled=False, cp_client=cp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # No Authorization header at all — mirrors local dev without Keycloak.
        resp = await client.post(f"/evaluations/{EVALUATION_ID}/runs", json=RUN_BODY)

    assert resp.status_code == 202
    assert len(cp_client.received_auths) == 1
    assert isinstance(cp_client.received_auths[0], NoAuthentication)


@pytest.mark.asyncio
async def test_two_requests_with_different_bearer_tokens_do_not_leak_into_each_other():
    cp_client = _RecordingControlPlaneClient()
    app = _build_app(security_enabled=True, cp_client=cp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_a = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer token-A"},
        )
        resp_b = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer token-B"},
        )

    assert resp_a.status_code == 202
    assert resp_b.status_code == 202
    tokens: list[str] = []
    for auth in cp_client.received_auths:
        assert isinstance(auth, UserAuthentication)
        tokens.append(auth.authorization_header)
    assert tokens == ["Bearer token-A", "Bearer token-B"]


@pytest.mark.asyncio
async def test_upstream_403_returns_the_exact_structured_envelope_and_status():
    app = _build_app(security_enabled=True, cp_client=_ForbiddenControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 403
    assert resp.json() == {
        "detail": {
            "code": "target_forbidden",
            "message": "You do not have permission to use the selected target in this team.",
        }
    }


@pytest.mark.asyncio
async def test_inline_dataset_or_cases_payload_is_rejected() -> None:
    """EVAL-04: the old inline `dataset`/`cases` request shape no longer exists —
    a client still sending it must fail request validation (422), not be
    silently accepted or ignored."""
    cp_client = _RecordingControlPlaneClient()
    app = _build_app(security_enabled=True, cp_client=cp_client)
    transport = httpx.ASGITransport(app=app)
    body = {
        "team_id": "team-1",
        "target": {"kind": "managed_instance", "agent_instance_id": "inst-1"},
        "dataset": {"name": "ds1", "cases": [{"input": "q1"}]},
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=body,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 422
    assert cp_client.received_auths == []


@pytest.mark.asyncio
async def test_cross_team_evaluation_id_is_rejected() -> None:
    cp_client = _RecordingControlPlaneClient()
    other_team_evaluation_store = _FakeEvaluationStore(
        rows={EVALUATION_ID: _evaluation_row(team_id="team-2")}
    )
    app = _build_app(
        security_enabled=True,
        cp_client=cp_client,
        evaluation_store=other_team_evaluation_store,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 404
    assert resp.json() == {
        "detail": {
            "code": "evaluation_not_found",
            "message": "The selected evaluation could not be found.",
        }
    }
    # Never reached the target resolver — the evaluation check runs first.
    assert cp_client.received_auths == []


@pytest.mark.asyncio
async def test_unknown_evaluation_id_is_rejected_the_same_way_as_cross_team() -> None:
    cp_client = _RecordingControlPlaneClient()
    empty_evaluation_store = _FakeEvaluationStore(rows={})
    app = _build_app(
        security_enabled=True, cp_client=cp_client, evaluation_store=empty_evaluation_store
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "evaluation_not_found"


@pytest.mark.asyncio
async def test_run_copies_cases_from_the_referenced_evaluation() -> None:
    cp_client = _RecordingControlPlaneClient()
    store = _FakeStore()
    evaluation_store = _FakeEvaluationStore(
        rows={
            EVALUATION_ID: SimpleNamespace(
                evaluation_id=EVALUATION_ID,
                name="ds1",
                version="v1",
                team_id="team-1",
                origin="manual",
                completeness="complete",
                cases_json=json.dumps(
                    [
                        {"input": "q1", "expected_output": "a1"},
                        {"input": "q2", "expected_output": "a2"},
                    ]
                ),
            )
        }
    )
    app = _build_app(
        security_enabled=True,
        cp_client=cp_client,
        store=store,
        evaluation_store=evaluation_store,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 202
    assert [(c["input"], c["expected_output"]) for c in store.created_cases] == [
        ("q1", "a1"),
        ("q2", "a2"),
    ]
