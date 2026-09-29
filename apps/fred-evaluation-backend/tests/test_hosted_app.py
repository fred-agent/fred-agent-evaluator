"""The `evaluation` application surface: `/teams/{team_id}/...` behind Fred's host.

Drives the real hosted router over an in-process ASGI transport, on the real
schema (SQLite built from the ORM models) and real stores; only the Control
Plane is faked, so entitlement answers are deterministic.

It verifies the two gates every route carries:
- entitlement — admitted only when the Control Plane lists `evaluation` for the
  team, refused (never admitted) on a non-member, an ungranted team, or a
  Control Plane that is unreachable or answers nonsense;
- ownership — an evaluation or run of another team is 404, like a missing one,
  and is left untouched;
and that the team comes from the path, never from the body.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fred_core import KeycloakUser, get_config, get_current_user
from sqlalchemy.ext.asyncio import create_async_engine

from fred_evaluation_backend.evaluations import models as _ds_models  # noqa: F401
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneInvalidResponseError,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    normalize_unstructured_auth_error,
)
from fred_evaluation_backend.execution.outbound_auth import (
    NoAuthentication,
    UserAuthentication,
)
from fred_evaluation_backend.hosted.api import build_hosted_router
from fred_evaluation_backend.hosted.entitlement import require_entitled
from fred_evaluation_backend.runs import models as _run_models  # noqa: F401
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.api import build_evaluations_router
from fred_evaluation_backend.runs.base import Base
from fred_evaluation_backend.runs.schemas import ManagedInstanceTarget
from fred_evaluation_backend.runs.store import RunStore

BEARER = "Bearer alice-token"
HEADERS = {"Authorization": BEARER}


class _FakeControlPlane:
    """Grants per team; `failure` makes the entitlement call itself fail."""

    def __init__(
        self,
        grants: dict[str, set[str]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.grants = grants if grants is not None else {"team-1": {"evaluation"}}
        self.failure = failure
        self.entitlement_auth: list[object] = []

    async def list_team_application_ids(self, *, team_id: str, auth):
        self.entitlement_auth.append(auth)
        if self.failure is not None:
            raise self.failure
        return frozenset(self.grants.get(team_id, set()))

    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=True, name=team_id)

    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth, agent_model_override=None
    ):
        return SimpleNamespace(
            agent_instance_id=agent_instance_id,
            evaluate_url="http://agent/evaluate",
        )


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://cp.test/teams/team-1/applications")
    return httpx.HTTPStatusError(
        "control plane",
        request=request,
        response=httpx.Response(status, request=request),
    )


async def _stores():
    db = os.path.join(tempfile.mkdtemp(), "eval.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, EvaluationStore(engine), RunStore(engine)


def _app(engine, cp: _FakeControlPlane) -> FastAPI:
    app = FastAPI()
    app.include_router(build_hosted_router())
    # The existing surface, at its root, shares the run helpers with this one.
    app.include_router(build_evaluations_router())
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_current_user] = lambda: KeycloakUser(
        uid="alice", username="alice", roles=[], email="alice@test.example"
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=True)),
        worker=SimpleNamespace(max_concurrent_cases=1, judge_profiles={}),
    )
    app.state.db_engine = engine
    app.state.control_plane_client = cp
    app.state.analysis_client = object()  # reached only once a run is completed
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS
    )


async def _seed(evaluation_store: EvaluationStore, run_store: RunStore, team: str):
    """An evaluation of `team` with one run, created on the existing service path."""
    evaluation_id = f"eval-{team}"
    await evaluation_store.create_evaluation(
        evaluation_id=evaluation_id,
        name=f"golden-{team}",
        version="v1",
        team_id=team,
        created_by="bob",
        origin="upload",
        completeness="complete",
        cases_json=json.dumps([{"input": "q1", "expected_output": "a1"}]),
    )
    created = await service.start_run(
        evaluation_id=evaluation_id,
        team_id=team,
        target=ManagedInstanceTarget(kind="managed_instance", agent_instance_id="i-1"),
        created_by="bob",
        store=run_store,
        evaluation_store=evaluation_store,
        control_plane_client=cast(
            ControlPlaneClient, cast(object, _FakeControlPlane())
        ),
        auth=NoAuthentication(),
        profile="auto",
        judge_profile_id="mistral-small",
        agent_model_override=None,
        max_concurrency=1,
        metrics=["answer_relevancy"],
        custom_metrics=[],
    )
    return evaluation_id, created.run_id


def _code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


@pytest.mark.asyncio
async def test_an_entitled_team_works_its_evaluations_end_to_end():
    engine, _, run_store = await _stores()
    cp = _FakeControlPlane()
    async with _client(_app(engine, cp)) as client:
        created = await client.post(
            "/teams/team-1/evaluations",
            json={
                "name": "golden",
                "origin": "manual",
                "cases": [{"input": "q1", "expected_output": "a1"}],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["team_id"] == "team-1"
        evaluation_id = created.json()["evaluation_id"]

        listed = await client.get("/teams/team-1/evaluations")
        assert [e["evaluation_id"] for e in listed.json()["evaluations"]] == [
            evaluation_id
        ]

        started = await client.post(
            f"/teams/team-1/evaluations/{evaluation_id}/runs",
            json={
                "target": {"kind": "managed_instance", "agent_instance_id": "i-1"},
                "metrics": ["answer_relevancy"],
            },
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]

        run = await client.get(f"/teams/team-1/runs/{run_id}")
        runs = await client.get(f"/teams/team-1/evaluations/{evaluation_id}/runs")
        summary = await client.get(
            f"/teams/team-1/evaluations/{evaluation_id}/runs/summary"
        )
        cases = await client.get(f"/teams/team-1/runs/{run_id}/cases")
        report = await client.get(f"/teams/team-1/runs/{run_id}/report")

    assert run.status_code == 200 and run.json()["run_id"] == run_id
    assert [r["run_id"] for r in runs.json()["runs"]] == [run_id]
    assert summary.status_code == 200
    assert cases.json()["total"] == 1
    assert report.status_code == 200
    stored = await run_store.get_run(run_id)
    assert stored is not None and stored.team_id == "team-1"
    # The entitlement check propagates the caller's own token (RFC EVAL-AUTH).
    assert cp.entitlement_auth
    assert all(
        a == UserAuthentication(authorization_header=BEARER)
        for a in cp.entitlement_auth
    )


@pytest.mark.asyncio
async def test_the_team_comes_from_the_path_never_from_the_body():
    engine, evaluation_store, _ = await _stores()
    async with _client(_app(engine, _FakeControlPlane())) as client:
        response = await client.post(
            "/teams/team-1/evaluations",
            json={
                "team_id": "team-2",
                "name": "golden",
                "origin": "manual",
                "cases": [{"input": "q1"}],
            },
        )
    assert response.status_code == 422
    assert await evaluation_store.list_evaluations_by_team("team-2") == []


@pytest.mark.parametrize(
    ("cp", "status", "code"),
    [
        (
            _FakeControlPlane(grants={"team-1": {"other-app"}}),
            403,
            "application_not_granted",
        ),
        (_FakeControlPlane(failure=_status_error(403)), 403, "target_forbidden"),
        (
            _FakeControlPlane(failure=httpx.ConnectError("down")),
            503,
            "control_plane_unavailable",
        ),
        (
            _FakeControlPlane(failure=ControlPlaneInvalidResponseError("bad body")),
            502,
            "control_plane_invalid_response",
        ),
    ],
    ids=["not-granted", "not-a-member", "unreachable", "incoherent"],
)
@pytest.mark.asyncio
async def test_anything_but_a_clear_grant_is_refused(cp, status, code):
    engine, evaluation_store, run_store = await _stores()
    evaluation_id, run_id = await _seed(evaluation_store, run_store, "team-1")
    async with _client(_app(engine, cp)) as client:
        reads = [
            await client.get("/teams/team-1/evaluations"),
            await client.get(f"/teams/team-1/runs/{run_id}"),
        ]
        writes = [
            await client.post(
                "/teams/team-1/evaluations",
                json={"name": "x", "origin": "manual", "cases": [{"input": "q"}]},
            ),
            await client.delete(f"/teams/team-1/runs/{run_id}"),
            await client.delete(f"/teams/team-1/evaluations/{evaluation_id}"),
        ]
    for response in reads + writes:
        assert response.status_code == status, response.text
        assert _code(response) == code
    assert await run_store.get_run(run_id) is not None
    assert len(await evaluation_store.list_evaluations_by_team("team-1")) == 1


@pytest.mark.asyncio
async def test_another_teams_run_is_not_found_and_left_untouched():
    engine, evaluation_store, run_store = await _stores()
    _, run_id = await _seed(evaluation_store, run_store, "team-2")
    # team-1 is entitled; the run belongs to team-2.
    async with _client(_app(engine, _FakeControlPlane())) as client:
        responses = [
            await client.get(f"/teams/team-1/runs/{run_id}"),
            await client.get(f"/teams/team-1/runs/{run_id}/cases"),
            await client.get(f"/teams/team-1/runs/{run_id}/cases/any"),
            await client.get(f"/teams/team-1/runs/{run_id}/report"),
            await client.post(f"/teams/team-1/runs/{run_id}/cancel"),
            await client.post(f"/teams/team-1/runs/{run_id}/analyze"),
            await client.delete(f"/teams/team-1/runs/{run_id}"),
        ]
    for response in responses:
        assert response.status_code == 404, response.text
        assert _code(response) == "run_not_found"
    run = await run_store.get_run(run_id)
    assert run is not None and run.operational_state != "cancelled"


@pytest.mark.asyncio
async def test_another_teams_evaluation_is_not_found_and_left_untouched():
    engine, evaluation_store, run_store = await _stores()
    evaluation_id, run_id = await _seed(evaluation_store, run_store, "team-2")
    async with _client(_app(engine, _FakeControlPlane())) as client:
        responses = [
            await client.get(f"/teams/team-1/evaluations/{evaluation_id}/runs"),
            await client.get(f"/teams/team-1/evaluations/{evaluation_id}/runs/summary"),
            await client.post(
                f"/teams/team-1/evaluations/{evaluation_id}/runs",
                json={
                    "target": {"kind": "managed_instance", "agent_instance_id": "i-1"},
                    "metrics": ["answer_relevancy"],
                },
            ),
            await client.delete(f"/teams/team-1/evaluations/{evaluation_id}"),
        ]
    for response in responses:
        assert response.status_code == 404, response.text
        assert _code(response) == "evaluation_not_found"
    assert await evaluation_store.get_evaluation(evaluation_id) is not None
    assert [
        r.run_id for r in await run_store.list_runs_by_evaluation(evaluation_id)
    ] == [run_id]


def _hosted_routes() -> list[APIRoute]:
    return [r for r in build_hosted_router().routes if isinstance(r, APIRoute)]


def _depends_on(dependant: Dependant, call: object) -> bool:
    return any(d.call is call or _depends_on(d, call) for d in dependant.dependencies)


def test_every_hosted_route_is_gated_by_entitlement():
    """A route added later without the gate fails here, not in production."""
    routes = _hosted_routes()
    assert routes
    ungated = [r.path for r in routes if not _depends_on(r.dependant, require_entitled)]
    assert ungated == []


_RUN_SPEC = {
    "target": {"kind": "managed_instance", "agent_instance_id": "i-1"},
    "metrics": ["answer_relevancy"],
}


@pytest.mark.asyncio
async def test_no_hosted_route_reaches_another_teams_resource():
    """Every route naming an evaluation or a run, current and future, answers 404
    for another team's resource and leaves it as it was."""
    engine, evaluation_store, run_store = await _stores()
    evaluation_id, run_id = await _seed(evaluation_store, run_store, "team-2")
    before = await run_store.get_run(run_id)
    checked: list[str] = []
    async with _client(_app(engine, _FakeControlPlane())) as client:
        for route in _hosted_routes():
            if "{run_id}" not in route.path and "{evaluation_id}" not in route.path:
                continue
            path = route.path.format(
                team_id="team-1",
                evaluation_id=evaluation_id,
                run_id=run_id,
                case_id="any",
            )
            for method in sorted(route.methods or ()):
                body = (
                    _RUN_SPEC if path.endswith("/runs") and method == "POST" else None
                )
                response = await client.request(method, path, json=body)
                checked.append(f"{method} {route.path}")
                assert response.status_code == 404, (method, route.path, response.text)
                assert _code(response) in ("run_not_found", "evaluation_not_found")
    assert len(checked) == 11
    after = await run_store.get_run(run_id)
    assert after is not None and before is not None
    assert after.operational_state == before.operational_state
    assert await evaluation_store.get_evaluation(evaluation_id) is not None


@pytest.mark.asyncio
async def test_the_personal_alias_is_refused_before_asking_the_control_plane():
    """`personal` means a different team for every caller at the Control Plane,
    but one shared key here; it must never be admitted."""
    engine, _, _ = await _stores()
    cp = _FakeControlPlane(grants={"personal": {"evaluation"}})
    async with _client(_app(engine, cp)) as client:
        response = await client.get("/teams/personal/evaluations")
    assert response.status_code == 403
    assert _code(response) == "application_not_granted"
    assert cp.entitlement_auth == []


@pytest.mark.asyncio
async def test_both_surfaces_refuse_to_analyze_a_run_still_in_progress():
    engine, evaluation_store, run_store = await _stores()
    _, run_id = await _seed(evaluation_store, run_store, "team-1")
    async with _client(_app(engine, _FakeControlPlane())) as client:
        hosted = await client.post(f"/teams/team-1/runs/{run_id}/analyze")
        existing = await client.post(f"/runs/{run_id}/analyze")
    for response in (hosted, existing):
        assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_control_plane_client_lists_the_teams_application_ids(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "schema_version": "1",
                "items": [{"id": "evaluation"}, {"id": "information-systems"}],
            },
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=transport, **kw)
    )
    client = ControlPlaneClient(base_url="http://cp.test/control-plane/v1")
    ids = await client.list_team_application_ids(
        team_id="team-1", auth=UserAuthentication(authorization_header=BEARER)
    )

    assert ids == frozenset({"evaluation", "information-systems"})
    assert (
        str(seen[0].url) == "http://cp.test/control-plane/v1/teams/team-1/applications"
    )
    assert seen[0].headers["authorization"] == BEARER

    _ = await client.list_team_application_ids(
        team_id="a/../b?x#y", auth=NoAuthentication()
    )
    assert seen[1].url.raw_path == (
        b"/control-plane/v1/teams/a%2F..%2Fb%3Fx%23y/applications"
    )


@pytest.mark.asyncio
async def test_control_plane_client_rejects_a_malformed_application_list(monkeypatch):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"apps": []}))
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=transport, **kw)
    )
    client = ControlPlaneClient(base_url="http://cp.test/control-plane/v1")
    with pytest.raises(ControlPlaneInvalidResponseError):
        await client.list_team_application_ids(
            team_id="team-1", auth=NoAuthentication()
        )
