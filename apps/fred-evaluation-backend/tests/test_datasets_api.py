"""POST/GET /evaluation/v1/datasets — EVAL-04 first release.

Drives the real FastAPI route (`datasets/api.py` -> `datasets/service.py`) over
an in-process ASGI transport (no sockets, no real DB, no Temporal). The
`DatasetStore` is faked with a plain in-memory dict so persistence assertions
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

from fred_evaluation_backend.datasets.api import (
    _get_control_plane_client,
    _get_dataset_store,
    build_datasets_router,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    normalize_unstructured_auth_error,
)


class _InMemoryDatasetStore:
    """Real create/list/get semantics, backed by a dict instead of Postgres."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    async def create_dataset(self, **kwargs):
        row = SimpleNamespace(created_at=datetime.now(timezone.utc), **kwargs)
        self.rows[kwargs["dataset_id"]] = row
        return row

    async def get_dataset(self, dataset_id: str):
        return self.rows.get(dataset_id)

    async def list_datasets_by_team(self, team_id: str):
        return [row for row in self.rows.values() if row.team_id == team_id]


class _MemberControlPlaneClient:
    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=True)


class _NonMemberControlPlaneClient:
    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=False)


def _build_app(*, cp_client, store: _InMemoryDatasetStore | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(build_datasets_router())
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_current_user] = lambda: KeycloakUser(
        uid="alice", username="alice", roles=[], email="alice@test.example"
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=True))
    )
    app.dependency_overrides[_get_dataset_store] = lambda: (
        store or _InMemoryDatasetStore()
    )
    app.dependency_overrides[_get_control_plane_client] = lambda: cp_client
    return app


@pytest.mark.asyncio
async def test_dataset_created_via_post_persists_independently_of_any_campaign() -> (
    None
):
    """Requirement (1): a dataset created through POST /datasets is a
    standalone resource — nothing about its persistence depends on a campaign
    ever being created against it."""
    store = _InMemoryDatasetStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/datasets",
            json={
                "team_id": "team-1",
                "origin": "manual",
                "cases": [{"input": "q1", "expected_output": "a1"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )
        assert create_resp.status_code == 201
        dataset_id = create_resp.json()["dataset_id"]

        list_resp = await client.get(
            "/datasets",
            params={"team_id": "team-1"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert list_resp.status_code == 200
    ids = [d["dataset_id"] for d in list_resp.json()["datasets"]]
    assert dataset_id in ids
    assert dataset_id in store.rows  # persisted, not just echoed back


@pytest.mark.asyncio
async def test_manual_origin_derives_name_and_manual_prefix() -> None:
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/datasets",
            json={
                "team_id": "team-1",
                "origin": "manual",
                "cases": [{"input": "q1"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["origin"] == "manual"
    assert body["name"].startswith("Manual dataset — ")
    # No expected_output anywhere -> minimal, not complete.
    assert body["completeness"] == "minimal"


@pytest.mark.asyncio
async def test_upload_origin_derives_name_from_source_filename_and_is_complete() -> (
    None
):
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/datasets",
            json={
                "team_id": "team-1",
                "origin": "upload",
                "source_filename": "golden_set.json",
                "cases": [
                    {"input": "q1", "expected_output": "a1"},
                    {"input": "q2", "expected_output": "a2"},
                ],
            },
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["origin"] == "upload"
    assert body["name"] == "golden_set.json"
    # Every case has an expected_output -> complete.
    assert body["completeness"] == "complete"
    assert body["case_count"] == 2


@pytest.mark.asyncio
async def test_non_member_cannot_create_or_list_team_datasets() -> None:
    app = _build_app(cp_client=_NonMemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/datasets",
            json={"team_id": "team-1", "origin": "manual", "cases": [{"input": "q1"}]},
            headers={"Authorization": "Bearer alice-token"},
        )
        list_resp = await client.get(
            "/datasets",
            params={"team_id": "team-1"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert create_resp.status_code == 403
    assert list_resp.status_code == 403
