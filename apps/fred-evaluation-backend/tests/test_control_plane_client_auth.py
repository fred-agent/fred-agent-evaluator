"""ControlPlaneClient outbound-auth isolation (EVAL-AUTH RFC — issue #33).

Proves the client never relies on mutable shared state for authentication:
each call takes an explicit `OutboundAuth` and builds its headers/httpx.Auth
fresh, so two requests (even concurrent ones) using different identities
cannot leak into each other, and `ServiceAuthentication` never fires for a
client that has no M2M token provider configured (the API's client).

All calls run against `httpx.MockTransport` — no real socket is opened, so
these tests are safe to run with `--disable-socket`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Callable

import httpx
import pytest
from fred_core import M2MAuthConfig, M2MTokenProvider

from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.outbound_auth import (
    NoAuthentication,
    ServiceAuthentication,
    UserAuthentication,
)

Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)


class _SpyM2MProvider(M2MTokenProvider):
    """M2MTokenProvider stand-in that records whether it was ever asked for a token."""

    def __init__(self, token: str = "m2m-service-token") -> None:
        super().__init__(
            M2MAuthConfig(
                keycloak_realm_url="http://keycloak.test/realms/test",
                client_id="spy-client",
                secret_env="SPY_M2M_SECRET_ENV_UNUSED",
            )
        )
        self.token = token
        self.calls = 0

    async def get_token(self) -> str:
        self.calls += 1
        return self.token


def _managed_instance_response() -> dict[str, str]:
    return {"execute_url": "/agents/execute", "runtime_id": "rt-1", "team_id": "team-1"}


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Route every httpx.AsyncClient created inside ControlPlaneClient through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(**kwargs) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_user_authentication_sends_caller_header_and_never_touches_m2m(
    monkeypatch,
):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    _patch_transport(monkeypatch, handler)
    spy = _SpyM2MProvider()
    client = ControlPlaneClient(base_url="http://cp.test", m2m_token_provider=spy)

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=UserAuthentication(authorization_header="Bearer user-token-abc"),
    )

    assert seen_auth_headers == ["Bearer user-token-abc"]
    assert spy.calls == 0, "an interactive call must never request an M2M token"


@pytest.mark.asyncio
async def test_service_authentication_uses_the_worker_m2m_token(monkeypatch):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    _patch_transport(monkeypatch, handler)
    spy = _SpyM2MProvider(token="m2m-xyz")
    client = ControlPlaneClient(base_url="http://cp.test", m2m_token_provider=spy)

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=ServiceAuthentication(),
    )

    assert seen_auth_headers == ["Bearer m2m-xyz"]
    assert spy.calls == 1


@pytest.mark.asyncio
async def test_no_authentication_sends_no_authorization_header_at_all(monkeypatch):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")  # no M2M provider — dev mode

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=NoAuthentication(),
    )

    assert seen_auth_headers == [None]


@pytest.mark.asyncio
async def test_service_authentication_without_m2m_provider_fails_fast_not_silently(
    monkeypatch,
):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("request must never be sent")

    _patch_transport(monkeypatch, handler)
    # This mirrors the API's client (main.py): no M2M provider configured.
    client = ControlPlaneClient(base_url="http://cp.test")

    with pytest.raises(RuntimeError):
        await client.prepare_managed_instance_execution(
            team_id="team-1",
            agent_instance_id="inst-1",
            auth=ServiceAuthentication(),
        )


@pytest.mark.asyncio
async def test_sequential_requests_with_different_tokens_do_not_leak(monkeypatch):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=UserAuthentication(authorization_header="Bearer token-A"),
    )
    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=UserAuthentication(authorization_header="Bearer token-B"),
    )

    assert seen_auth_headers == ["Bearer token-A", "Bearer token-B"]


@pytest.mark.asyncio
async def test_concurrent_requests_with_different_tokens_do_not_leak(monkeypatch):
    seen_auth_headers: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        # Let the first-issued request (token-A) resolve second, so a shared
        # mutable header on the client would surface as cross-contamination.
        if request.headers.get("authorization") == "Bearer token-A":
            await asyncio.sleep(0.02)
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    _patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")

    await asyncio.gather(
        client.prepare_managed_instance_execution(
            team_id="team-1",
            agent_instance_id="inst-1",
            auth=UserAuthentication(authorization_header="Bearer token-A"),
        ),
        client.prepare_managed_instance_execution(
            team_id="team-1",
            agent_instance_id="inst-1",
            auth=UserAuthentication(authorization_header="Bearer token-B"),
        ),
    )

    assert sorted(h for h in seen_auth_headers if h is not None) == [
        "Bearer token-A",
        "Bearer token-B",
    ]
