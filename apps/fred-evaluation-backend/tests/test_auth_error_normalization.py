"""Evaluator boundary translation of fred-core's unstructured auth failures.

`fred_core.get_current_user` runs as a route dependency, resolved by FastAPI
*before* any route body — so a failure there never reaches this app's own
resolvers or error mapping (`execution/evaluator_errors.py`). It raises a
plain `HTTPException(detail="...")` (a bare string, e.g. "No authentication
token provided"), which would otherwise violate this API's one documented
error envelope. `main.py` registers `normalize_unstructured_auth_error` as the
app's `HTTPException` handler to close that gap at the evaluator's own public
boundary — without touching fred-core's own authentication decisions.

These tests drive the real `start_run` route over an in-process ASGI
transport (no sockets, no DB, no live Keycloak/JWKS).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Callable

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fred_core import get_config, get_current_user, get_user_store
from pytest import MonkeyPatch

from fred_evaluation_backend.execution.evaluator_errors import (
    EvaluatorErrorDetail,
    normalize_unstructured_auth_error,
)
from fred_evaluation_backend.runs.api import (
    _get_control_plane_client,
    _get_evaluation_catalog_store,
    _get_run_store,
    build_evaluations_router,
)

EVALUATION_ID = "eval-ds-1"
RUN_BODY = {
    "team_id": "team-1",
    "target": {"kind": "managed_instance", "agent_instance_id": "inst-1"},
}


class _FakeStore:
    async def create_run(self, **kwargs: object) -> None:
        return None

    async def create_case(self, **kwargs: object) -> None:
        return None


class _FakeEvaluationStore:
    async def get_evaluation(self, evaluation_id: str) -> object:
        return SimpleNamespace(
            evaluation_id=evaluation_id,
            team_id="team-1",
            name="ds1",
            version="v1",
            cases_json='[{"input": "q1"}]',
        )


class _UnreachedControlPlaneClient:
    """The route body must never run in these tests — reaching it is a bug."""

    async def prepare_managed_instance_execution(self, **kwargs: object) -> object:
        raise AssertionError("route body reached — auth should have failed first")

    async def prepare_runtime_agent_execution(self, **kwargs: object) -> object:
        raise AssertionError("route body reached — auth should have failed first")


def _build_app(
    *, override_get_current_user: Callable[..., object] | None = None
) -> FastAPI:
    app = FastAPI()
    app.include_router(build_evaluations_router())
    # Mirrors main.py's create_app() wiring exactly.
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=True)),
        app=SimpleNamespace(gcu_version=None),
    )
    # get_current_user's own sub-dependency — unrelated to what's under test here.
    app.dependency_overrides[get_user_store] = lambda: None
    app.dependency_overrides[_get_run_store] = lambda: _FakeStore()
    app.dependency_overrides[_get_evaluation_catalog_store] = lambda: (
        _FakeEvaluationStore()
    )
    app.dependency_overrides[_get_control_plane_client] = lambda: (
        _UnreachedControlPlaneClient()
    )
    if override_get_current_user is not None:
        app.dependency_overrides[get_current_user] = override_get_current_user
    return app


@pytest.mark.asyncio
async def test_missing_authorization_header_hits_the_real_boundary_and_returns_structured_401(
    monkeypatch: MonkeyPatch,
) -> None:
    """get_current_user is NOT overridden — this is fred-core's real dependency,
    which raises `HTTPException(401, "No authentication token provided")`."""
    monkeypatch.setattr("fred_core.security.oidc.KEYCLOAK_ENABLED", True)
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs", json=RUN_BODY
        )  # no header at all

    assert resp.status_code == 401
    assert resp.json() == {
        "detail": {
            "code": "authentication_required",
            "message": "A valid Authorization Bearer token is required.",
        }
    }


@pytest.mark.asyncio
async def test_missing_authorization_header_preserves_www_authenticate(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("fred_core.security.oidc.KEYCLOAK_ENABLED", True)
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/evaluations/{EVALUATION_ID}/runs", json=RUN_BODY)

    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_unstructured_403_from_auth_dependency_returns_structured_access_forbidden() -> (
    None
):
    async def _raise_unstructured_403() -> object:
        # Mirrors fred-core's own shape (e.g. "user_not_whitelisted" /
        # "user_not_accept_gcu"): a bare string detail, no headers. fred-core's
        # own whitelist/GCU decision logic is out of scope — this proves the
        # evaluator's own translation of whatever unstructured HTTPException
        # a fred-core auth dependency raises.
        raise HTTPException(status_code=403, detail="user_not_whitelisted")

    app = _build_app(override_get_current_user=_raise_unstructured_403)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer irrelevant"},
        )

    assert resp.status_code == 403
    assert resp.json() == {
        "detail": {
            "code": "access_forbidden",
            "message": "You do not have permission to perform this action.",
        }
    }


@pytest.mark.asyncio
async def test_already_structured_evaluator_error_passes_through_unchanged() -> None:
    """The handler must not alter an HTTPException this app already built."""

    async def _raise_structured() -> object:
        raise HTTPException(
            status_code=403,
            detail=EvaluatorErrorDetail(
                code="target_forbidden", message="original message"
            ).model_dump(),
        )

    app = _build_app(override_get_current_user=_raise_structured)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/evaluations/{EVALUATION_ID}/runs",
            json=RUN_BODY,
            headers={"Authorization": "Bearer irrelevant"},
        )

    assert resp.status_code == 403
    assert resp.json() == {
        "detail": {"code": "target_forbidden", "message": "original message"}
    }
