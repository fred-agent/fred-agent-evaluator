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
from typing import Callable, override

import httpx
import pytest
from fred_core import M2MAuthConfig, M2MTokenProvider
from fred_pod.security.backend_to_backend_auth import TokenLease

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

    @override
    async def get_token_lease(self) -> TokenLease:
        # M2MBearerAuth authenticates through a lease, not get_token().
        return TokenLease(await self.get_token(), 0)


def _managed_instance_response() -> dict[str, str]:
    return {
        "execute_url": "/agents/execute",
        "runtime_id": "rt-1",
        "space_id": "team-1",
        "agent_instance_id": "inst-1",
    }


def patch_transport(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Route every httpx.AsyncClient created inside ControlPlaneClient through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(**kwargs) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_user_authentication_sends_caller_header_and_never_touches_m2m(
    monkeypatch: pytest.MonkeyPatch,
):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    patch_transport(monkeypatch, handler)
    spy = _SpyM2MProvider()
    client = ControlPlaneClient(
        runtime_base_url="http://runtime.test",
        base_url="http://cp.test",
        m2m_token_provider=spy,
    )

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=UserAuthentication(authorization_header="Bearer user-token-abc"),
    )

    assert seen_auth_headers == ["Bearer user-token-abc"]
    assert spy.calls == 0, "an interactive call must never request an M2M token"


@pytest.mark.asyncio
async def test_preparation_rejects_service_identity_even_with_m2m_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Browser-only route must not be called by the worker")

    patch_transport(monkeypatch, handler)
    spy = _SpyM2MProvider()
    client = ControlPlaneClient(base_url="http://cp.test", m2m_token_provider=spy)
    with pytest.raises(RuntimeError, match="API caller"):
        _ = await client.prepare_managed_instance_execution(
            team_id="team-1", agent_instance_id="inst-1", auth=ServiceAuthentication()
        )
    assert spy.calls == 0


@pytest.mark.asyncio
async def test_no_authentication_sends_no_authorization_header_at_all(
    monkeypatch: pytest.MonkeyPatch,
):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(
        runtime_base_url="http://runtime.test", base_url="http://cp.test"
    )  # no M2M provider — dev mode

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=NoAuthentication(),
    )

    assert seen_auth_headers == [None]


@pytest.mark.asyncio
async def test_service_authentication_without_m2m_provider_fails_fast_not_silently(
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("request must never be sent")

    patch_transport(monkeypatch, handler)
    # This mirrors the API's client (main.py): no M2M provider configured.
    client = ControlPlaneClient(
        runtime_base_url="http://runtime.test", base_url="http://cp.test"
    )

    with pytest.raises(RuntimeError):
        _ = await client.prepare_managed_instance_execution(
            team_id="team-1",
            agent_instance_id="inst-1",
            auth=ServiceAuthentication(),
        )


@pytest.mark.asyncio
async def test_preparation_sends_no_query_parameters(monkeypatch: pytest.MonkeyPatch):
    seen_queries: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.query)
        return httpx.Response(200, json=_managed_instance_response())

    patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(
        runtime_base_url="http://runtime.test", base_url="http://cp.test"
    )

    await client.prepare_managed_instance_execution(
        team_id="team-1",
        agent_instance_id="inst-1",
        auth=NoAuthentication(),
    )

    assert seen_queries == [b""]


@pytest.mark.asyncio
async def test_sequential_requests_with_different_tokens_do_not_leak(
    monkeypatch: pytest.MonkeyPatch,
):
    seen_auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(
        runtime_base_url="http://runtime.test", base_url="http://cp.test"
    )

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
async def test_concurrent_requests_with_different_tokens_do_not_leak(
    monkeypatch: pytest.MonkeyPatch,
):
    seen_auth_headers: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        # Let the first-issued request (token-A) resolve second, so a shared
        # mutable header on the client would surface as cross-contamination.
        if request.headers.get("authorization") == "Bearer token-A":
            await asyncio.sleep(0.02)
        seen_auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_managed_instance_response())

    patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(
        runtime_base_url="http://runtime.test", base_url="http://cp.test"
    )

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "execute_url,expected",
    [
        ("/pod/agents/execute", "http://runtime.test/pod/agents/evaluate"),
        ("http://pod.test/base/agents/execute", "http://pod.test/base/agents/evaluate"),
    ],
)
async def test_prepare_resolves_weaver_routing(
    monkeypatch: pytest.MonkeyPatch, execute_url: str, expected: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert (
            request.url.path
            == "/spaces/team-1/agent-instances/inst-1/prepare-execution"
        )
        assert not request.url.query
        return httpx.Response(
            200, json={**_managed_instance_response(), "execute_url": execute_url}
        )

    patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(
        base_url="http://cp.test", runtime_base_url="http://runtime.test"
    )
    prep = await client.prepare_managed_instance_execution(
        team_id="team-1", agent_instance_id="inst-1", auth=NoAuthentication()
    )
    assert prep.space_id == "team-1"
    assert prep.runtime_id == "rt-1"
    assert prep.evaluate_url == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"allowed": "false"}, {"allowed": 1}, {}, []])
async def test_space_authorization_rejects_malformed_decisions(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    from fred_evaluation_backend.execution.control_plane_client import (
        ControlPlaneInvalidResponseError,
    )

    patch_transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(ControlPlaneInvalidResponseError):
        _ = await ControlPlaneClient(base_url="http://cp.test").authorize_space(
            space_id="space-1", auth=NoAuthentication()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,allowed,expected", [(200, False, 403), (404, False, 404), (200, True, None)]
)
async def test_space_permission_decision(
    monkeypatch: pytest.MonkeyPatch, status: int, allowed: bool, expected: int | None
) -> None:
    import json

    from fastapi import HTTPException

    from fred_evaluation_backend.execution.team_resolver import resolve_team_membership

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/authorize/space"
        assert json.loads(request.content) == {
            "space_id": "space-1",
            "permission": "run_evaluations",
        }
        assert request.headers["authorization"] == "Bearer caller-token"
        return httpx.Response(status, json={"allowed": allowed})

    patch_transport(monkeypatch, handler)
    client = ControlPlaneClient(base_url="http://cp.test")
    auth = UserAuthentication(authorization_header="Bearer caller-token")
    if expected is None:
        await resolve_team_membership(
            team_id="space-1", control_plane_client=client, auth=auth
        )
    else:
        with pytest.raises(HTTPException) as exc:
            await resolve_team_membership(
                team_id="space-1", control_plane_client=client, auth=auth
            )
        assert exc.value.status_code == expected
