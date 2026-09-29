"""`/evaluation/v1` routes naming a run, a task or an evaluation are team-checked.

Those ids are global: authentication alone let any caller read, cancel or delete
another team's run by knowing its id. Every such route now asks the Control
Plane whether the caller belongs to the resource's own team.

Real schema (SQLite built from the ORM models) and real stores; only the Control
Plane is faked. The route list is not written by hand: every route of the three
`/evaluation/v1` routers carrying an id is driven, so a route added later
without the check fails here.
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
from fastapi.routing import APIRoute
from fred_core import KeycloakUser, get_config, get_current_user
from sqlalchemy.ext.asyncio import create_async_engine

from fred_evaluation_backend.evaluations import models as _ds_models  # noqa: F401
from fred_evaluation_backend.evaluations.api import build_evaluation_catalog_router
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import (
    normalize_unstructured_auth_error,
)
from fred_evaluation_backend.execution.outbound_auth import NoAuthentication
from fred_evaluation_backend.runs import models as _run_models  # noqa: F401
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.api import build_evaluations_router
from fred_evaluation_backend.runs.base import Base
from fred_evaluation_backend.runs.schemas import ManagedInstanceTarget
from fred_evaluation_backend.runs.store import RunStore
from fred_evaluation_backend.tasks.api import build_tasks_router

HEADERS = {"Authorization": "Bearer alice-token"}


class _ControlPlane:
    """Alice belongs to team-1 only."""

    def __init__(self, member_of: frozenset[str] = frozenset({"team-1"})) -> None:
        self.member_of = member_of

    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(
            team_id=team_id, is_member=team_id in self.member_of, name=team_id
        )

    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth, agent_model_override=None
    ):
        if team_id not in self.member_of:
            request = httpx.Request("POST", "http://cp.test/prepare-execution")
            raise httpx.HTTPStatusError(
                "forbidden",
                request=request,
                response=httpx.Response(403, request=request),
            )
        return SimpleNamespace(
            agent_instance_id=agent_instance_id, evaluate_url="http://agent/evaluate"
        )


def _routers():
    return (
        build_evaluations_router(),
        build_evaluation_catalog_router(),
        build_tasks_router(),
    )


def _app(engine) -> FastAPI:
    app = FastAPI()
    for router in _routers():
        app.include_router(router)
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_current_user] = lambda: KeycloakUser(
        uid="alice", username="alice", roles=[], email="alice@test.example"
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=True)),
        worker=SimpleNamespace(max_concurrent_cases=1, judge_profiles={}),
        observability=SimpleNamespace(tracer="logging"),
    )
    app.state.db_engine = engine
    app.state.control_plane_client = _ControlPlane()
    app.state.analysis_client = object()
    return app


async def _stores():
    db = os.path.join(tempfile.mkdtemp(), "eval.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, EvaluationStore(engine), RunStore(engine)


async def _seed(evaluation_store: EvaluationStore, run_store: RunStore, team: str):
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
            ControlPlaneClient, cast(object, _ControlPlane(frozenset({team})))
        ),
        auth=NoAuthentication(),
        profile="auto",
        judge_profile_id="mistral-small",
        agent_model_override=None,
        max_concurrency=1,
        metrics=["answer_relevancy"],
        custom_metrics=[],
    )
    return evaluation_id, created.run_id, created.task_id


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS
    )


_ID_PARAMS = ("{run_id}", "{task_id}", "{evaluation_id}")


@pytest.mark.asyncio
async def test_no_route_reaches_another_teams_run_task_or_evaluation():
    engine, evaluation_store, run_store = await _stores()
    evaluation_id, run_id, task_id = await _seed(evaluation_store, run_store, "team-2")
    before = await run_store.get_run(run_id)
    checked: list[str] = []
    async with _client(_app(engine)) as client:
        for router in _routers():
            for route in router.routes:
                if not isinstance(route, APIRoute):
                    continue
                if not any(p in route.path for p in _ID_PARAMS):
                    continue
                path = route.path.format(
                    evaluation_id=evaluation_id,
                    run_id=run_id,
                    task_id=task_id,
                    case_id="any",
                )
                for method in sorted(route.methods or ()):
                    body = None
                    if (
                        route.path == "/evaluations/{evaluation_id}/runs"
                        and method == "POST"
                    ):
                        body = {
                            "team_id": "team-2",
                            "target": {
                                "kind": "managed_instance",
                                "agent_instance_id": "i-1",
                            },
                            "metrics": ["answer_relevancy"],
                        }
                    response = await client.request(method, path, json=body)
                    checked.append(f"{method} {route.path}")
                    assert response.status_code == 403, (
                        method,
                        route.path,
                        response.text,
                    )
                    assert response.json()["detail"]["code"] == "target_forbidden"
    assert len(checked) == 17, checked
    after = await run_store.get_run(run_id)
    assert after is not None and before is not None
    assert after.operational_state == before.operational_state
    assert after.analysis_json is None
    assert await evaluation_store.get_evaluation(evaluation_id) is not None
    assert len(await run_store.list_runs_by_evaluation(evaluation_id)) == 1


@pytest.mark.asyncio
async def test_listing_another_teams_tasks_is_refused():
    engine, evaluation_store, run_store = await _stores()
    _ = await _seed(evaluation_store, run_store, "team-2")
    async with _client(_app(engine)) as client:
        response = await client.get(
            "/tasks", params={"scope": "team", "team_id": "team-2"}
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "target_forbidden"


@pytest.mark.asyncio
async def test_a_member_still_reaches_their_own_teams_runs_and_tasks():
    engine, evaluation_store, run_store = await _stores()
    evaluation_id, run_id, task_id = await _seed(evaluation_store, run_store, "team-1")
    async with _client(_app(engine)) as client:
        responses = [
            await client.get(f"/runs/{run_id}"),
            await client.get(f"/runs/{run_id}/cases"),
            await client.get(f"/runs/{run_id}/report"),
            await client.get(f"/evaluations/{evaluation_id}/runs"),
            await client.get(f"/evaluations/{evaluation_id}/runs/summary"),
            await client.get(f"/tasks/{task_id}"),
            await client.get(f"/tasks/{task_id}/latest"),
            await client.get("/tasks", params={"scope": "team", "team_id": "team-1"}),
        ]
        cancelled = await client.post(f"/runs/{run_id}/cancel")
    for response in responses:
        assert response.status_code == 200, (str(response.url), response.text)
    assert cancelled.status_code == 202
    assert [t["task_id"] for t in responses[-1].json()["tasks"]] == [task_id]
