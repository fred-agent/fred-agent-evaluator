"""Typed Control Plane error classification (EVAL-AUTH RFC — issue #33, part 3).

Replaces the old blanket `except Exception: 422 "not available"` handling.
Proves each upstream failure category maps to the documented evaluator status
+ stable error code, that the UUID is never the message's main explanation,
and that logs never contain the caller's bearer token.
"""

from __future__ import annotations

from typing import Callable

import httpx
import pytest
from fastapi import HTTPException
from pytest import MonkeyPatch

from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import parse_error_detail
from fred_evaluation_backend.execution.outbound_auth import (
    ServiceAuthentication,
    UserAuthentication,
)
from fred_evaluation_backend.execution.runtime_resolver import resolve_managed_instance

AUTH = UserAuthentication(authorization_header="Bearer secret-user-token")
TARGET_UUID = "11111111-1111-1111-1111-111111111111"

Handler = Callable[[httpx.Request], httpx.Response]


def _patch_transport(monkeypatch: MonkeyPatch, handler: Handler) -> None:
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(**kwargs) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.parametrize(
    "upstream_status,expected_status,expected_code",
    [
        (401, 401, "control_plane_authentication_failed"),
        (403, 403, "target_forbidden"),
        (404, 404, "target_not_found"),
        (409, 409, "target_unavailable"),
        (422, 422, "target_invalid"),
        (500, 503, "control_plane_unavailable"),
        (503, 503, "control_plane_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_managed_instance_upstream_status_mapping(
    monkeypatch: MonkeyPatch,
    upstream_status: int,
    expected_status: int,
    expected_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"detail": "opaque upstream body"})

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    with pytest.raises(HTTPException) as exc_info:
        await resolve_managed_instance(
            team_id="team-1",
            agent_instance_id=TARGET_UUID,
            control_plane_client=client,
            auth=AUTH,
        )

    exc = exc_info.value
    detail = parse_error_detail(exc)
    assert exc.status_code == expected_status
    assert detail.code == expected_code
    # The message must be actionable, not the raw UUID as its main explanation.
    assert TARGET_UUID not in detail.message


@pytest.mark.asyncio
async def test_timeout_maps_to_503_unavailable(monkeypatch: MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    with pytest.raises(HTTPException) as exc_info:
        await resolve_managed_instance(
            team_id="team-1",
            agent_instance_id="inst-1",
            control_plane_client=client,
            auth=AUTH,
        )
    assert exc_info.value.status_code == 503
    assert parse_error_detail(exc_info.value).code == "control_plane_unavailable"


@pytest.mark.asyncio
async def test_connection_failure_maps_to_503_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    with pytest.raises(HTTPException) as exc_info:
        await resolve_managed_instance(
            team_id="team-1",
            agent_instance_id="inst-1",
            control_plane_client=client,
            auth=AUTH,
        )
    assert exc_info.value.status_code == 503
    assert parse_error_detail(exc_info.value).code == "control_plane_unavailable"


@pytest.mark.asyncio
async def test_malformed_upstream_response_maps_to_dedicated_502(
    monkeypatch: MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 200 OK but missing the required "execute_url" field.
        return httpx.Response(200, json={"unexpected": "shape"})

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    with pytest.raises(HTTPException) as exc_info:
        await resolve_managed_instance(
            team_id="team-1",
            agent_instance_id="inst-1",
            control_plane_client=client,
            auth=AUTH,
        )
    assert exc_info.value.status_code == 502
    assert parse_error_detail(exc_info.value).code == "control_plane_invalid_response"


@pytest.mark.asyncio
async def test_local_configuration_defect_propagates_unchanged_not_502(
    monkeypatch: MonkeyPatch,
) -> None:
    """A local/programming defect (e.g. missing M2M config) must not be relabelled
    as a Control Plane failure — it is not caused by the Control Plane at all."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("request must never be sent — fails before any I/O")

    _patch_transport(monkeypatch, handler)
    # No M2M provider configured: ServiceAuthentication raises RuntimeError inside
    # the client, *before* any HTTP call — a local configuration defect, not an
    # upstream Control Plane failure.
    client = ControlPlaneClient(base_url="http://cp.test")

    with pytest.raises(RuntimeError):
        await resolve_managed_instance(
            team_id="team-1",
            agent_instance_id="inst-1",
            control_plane_client=client,
            auth=ServiceAuthentication(),
        )


@pytest.mark.asyncio
async def test_error_logs_never_contain_the_bearer_token(
    monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    with caplog.at_level("ERROR"):
        with pytest.raises(HTTPException):
            await resolve_managed_instance(
                team_id="team-1",
                agent_instance_id="inst-1",
                control_plane_client=client,
                auth=AUTH,
            )

    assert "secret-user-token" not in caplog.text
    assert "Bearer" not in caplog.text
