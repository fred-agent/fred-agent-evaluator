"""POST/GET /evaluation/v1/evaluations — evaluation catalog surface.

Drives the real FastAPI route (`datasets/api.py` -> `datasets/service.py`) over
an in-process ASGI transport (no sockets, no real DB, no Temporal). The
`EvaluationStore` is faked with a plain in-memory dict so persistence assertions
don't depend on a live Postgres; the Control Plane client is faked so
team-membership checks are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fred_core import KeycloakUser, get_config, get_current_user

from fred_evaluation_backend.evaluations.api import (
    _get_control_plane_client,
    _get_evaluation_catalog_store,
    build_evaluation_catalog_router,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    normalize_unstructured_auth_error,
)


class _InMemoryEvaluationStore:
    """Real create/list/get semantics, backed by a dict instead of Postgres."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    async def create_evaluation(self, **kwargs):
        row = SimpleNamespace(created_at=datetime.now(timezone.utc), **kwargs)
        self.rows[kwargs["evaluation_id"]] = row
        return row

    async def get_evaluation(self, evaluation_id: str):
        return self.rows.get(evaluation_id)

    async def list_evaluations_by_team(self, team_id: str):
        return [row for row in self.rows.values() if row.team_id == team_id]

    async def get_latest_version_number(self, team_id: str, name: str) -> int:
        numbers = [
            int(str(r.version).lstrip("v"))
            for r in self.rows.values()
            if r.team_id == team_id and r.name == name
        ]
        return max(numbers, default=0)


class _MemberControlPlaneClient:
    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=True)


class _NonMemberControlPlaneClient:
    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=False)


def _build_app(*, cp_client, store: _InMemoryEvaluationStore | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(build_evaluation_catalog_router())
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_current_user] = lambda: KeycloakUser(
        uid="alice", username="alice", roles=[], email="alice@test.example"
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=True))
    )
    app.dependency_overrides[_get_evaluation_catalog_store] = lambda: (
        store or _InMemoryEvaluationStore()
    )
    app.dependency_overrides[_get_control_plane_client] = lambda: cp_client
    return app


@pytest.mark.asyncio
async def test_evaluation_created_via_post_persists_independently_of_any_run() -> (
    None
):
    """A created evaluation is standalone; it does not depend on a run to exist."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/evaluations",
            json={
                "team_id": "team-1",
                "name": "usage-arxivai",
                "origin": "manual",
                "cases": [{"input": "q1", "expected_output": "a1"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )
        assert create_resp.status_code == 201
        evaluation_id = create_resp.json()["evaluation_id"]

        list_resp = await client.get(
            "/evaluations",
            params={"team_id": "team-1"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert list_resp.status_code == 200
    ids = [d["evaluation_id"] for d in list_resp.json()["evaluations"]]
    assert evaluation_id in ids
    assert evaluation_id in store.rows  # persisted, not just echoed back


@pytest.mark.asyncio
async def test_name_is_user_supplied_and_first_import_is_v1() -> None:
    """EVAL-05: the name comes from the user (not derived), and a brand-new name
    starts at v1. Completeness is still derived from the cases."""
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/evaluations",
            json={
                "team_id": "team-1",
                "name": "golden-set",
                "origin": "upload",
                "cases": [
                    {"input": "q1", "expected_output": "a1"},
                    {"input": "q2", "expected_output": "a2"},
                ],
            },
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "golden-set"
    assert body["version"] == "v1"
    # EVAL-05: the evaluation format is self-contained — it carries its author.
    assert body["author"] == "alice"
    # Every case has an expected_output -> complete.
    assert body["completeness"] == "complete"
    assert body["case_count"] == 2


@pytest.mark.asyncio
async def test_reimporting_same_name_creates_next_version_and_new_id() -> None:
    """EVAL-05 (§8.5): re-importing the same name in the same team creates v2, a
    distinct row with its own id. Different name stays at v1."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)

    async def _create(name: str) -> dict:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/evaluations",
                json={
                    "team_id": "team-1",
                    "name": name,
                    "origin": "manual",
                    "cases": [{"input": "q1"}],
                },
                headers={"Authorization": "Bearer alice-token"},
            )
        assert resp.status_code == 201
        return resp.json()

    first = await _create("usage-arxivai")
    second = await _create("usage-arxivai")
    other = await _create("usage-rag")

    assert first["version"] == "v1"
    assert second["version"] == "v2"  # same name -> next version
    assert second["evaluation_id"] != first["evaluation_id"]  # its own row
    assert other["version"] == "v1"  # a different name is independent


@pytest.mark.asyncio
async def test_non_member_cannot_create_or_list_team_datasets() -> None:
    app = _build_app(cp_client=_NonMemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/evaluations",
            json={
                "team_id": "team-1",
                "name": "x",
                "origin": "manual",
                "cases": [{"input": "q1"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )
        list_resp = await client.get(
            "/evaluations",
            params={"team_id": "team-1"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert create_resp.status_code == 403
    assert list_resp.status_code == 403
