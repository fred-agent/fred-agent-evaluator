from __future__ import annotations

import logging
from urllib.parse import quote, urljoin, urlsplit

import httpx
from fred_core import M2MBearerAuth, M2MTokenProvider
from pydantic import BaseModel, StrictBool

from fred_evaluation_backend.execution.outbound_auth import (
    NoAuthentication,
    OutboundAuth,
    ServiceAuthentication,
    UserAuthentication,
)

logger = logging.getLogger(__name__)


class ControlPlaneInvalidResponseError(Exception):
    """A successful (2xx) Control Plane response could not be parsed or validated.

    Deliberately narrow: raised only for response decode/shape failures at this
    client's boundary, never for local programming or configuration defects
    (those must propagate as themselves, e.g. `RuntimeError`).
    """


class ControlPlaneEvaluationUnsupportedError(Exception):
    """The selected runtime does not expose a synchronous evaluation endpoint."""


class _ExecutionRouting(BaseModel):
    agent_instance_id: str
    runtime_id: str
    space_id: str
    execute_url: str | None


class ManagedInstanceExecutionPreparation(BaseModel):
    agent_instance_id: str
    runtime_id: str
    space_id: str
    evaluate_url: str


class SpaceAuthorization(BaseModel):
    allowed: StrictBool


class SpaceDetails(BaseModel):
    name: str


class TeamAgentInstance(BaseModel):
    """One managed agent instance a team can evaluate (Control Plane projection)."""

    agent_instance_id: str
    display_name: str
    role: str | None = None


class _AgentInstancePage(BaseModel):
    items: list[TeamAgentInstance]
    next_cursor: str | None


class TeamModelProfile(BaseModel):
    """One chat model profile the team is `can_use`-enabled for.

    `name` is an i18n key of Fred's own frontend, which this application cannot
    translate; `profile_id` is what a run's `agent_model_override` names.
    """

    profile_id: str
    name: str


class ControlPlaneClient:
    """Control Plane HTTP client.

    Outbound authentication (`OutboundAuth`) is passed explicitly on every call
    — never stored as request state on the client. `self` only ever holds
    connection configuration (base URLs, the worker's M2M token provider); a
    user's bearer token is request-scoped and lives only in the `OutboundAuth`
    value passed to that call, so two concurrent requests using different
    tokens cannot leak into each other.
    """

    def __init__(
        self,
        base_url: str,
        *,
        runtime_base_url: str = "",
        m2m_token_provider: M2MTokenProvider | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._runtime_base_url = runtime_base_url.rstrip("/")
        self._m2m_token_provider = m2m_token_provider
        self._m2m_auth = (
            M2MBearerAuth(m2m_token_provider) if m2m_token_provider else None
        )

    @property
    def m2m_token_provider(self) -> M2MTokenProvider | None:
        """The worker's own M2M token provider — for downstream calls the worker
        makes directly (e.g. to fred-runtime's `/agents/evaluate`), not for this
        client's own outbound calls, which always take an explicit `auth` arg."""
        return self._m2m_token_provider

    def _build_request(
        self, auth: OutboundAuth
    ) -> tuple[dict[str, str], httpx.Auth | None]:
        headers = {"Content-Type": "application/json"}
        if isinstance(auth, UserAuthentication):
            headers["Authorization"] = auth.authorization_header
            return headers, None
        if isinstance(auth, ServiceAuthentication):
            if self._m2m_auth is None:
                raise RuntimeError(
                    "ControlPlaneClient has no M2M token provider configured; "
                    "cannot use ServiceAuthentication."
                )
            return headers, self._m2m_auth
        if isinstance(auth, NoAuthentication):
            return headers, None
        raise TypeError(f"Unsupported outbound auth: {auth!r}")  # pragma: no cover

    @staticmethod
    async def _post(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        http_auth: httpx.Auth | None,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        # httpx's `post()` convenience method doesn't accept `auth=None` (only its
        # lower-level `request()` does) — omit the kwarg instead, which is
        # equivalent here since these clients never carry a default auth.
        if http_auth is not None:
            return await client.post(url, headers=headers, auth=http_auth, json=json)
        return await client.post(url, headers=headers, json=json)

    @staticmethod
    async def _get(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        http_auth: httpx.Auth | None,
    ) -> httpx.Response:
        if http_auth is not None:
            return await client.get(url, headers=headers, auth=http_auth)
        return await client.get(url, headers=headers)

    async def prepare_managed_instance_execution(
        self,
        *,
        team_id: str,
        agent_instance_id: str,
        auth: OutboundAuth,
    ) -> ManagedInstanceExecutionPreparation:
        # Weaver preparation is an admitted-user route, never a worker route.
        if isinstance(auth, ServiceAuthentication):
            raise RuntimeError("prepare-execution requires the API caller's identity.")
        url = (
            f"{self._base_url}/spaces/{quote(team_id, safe='')}"
            f"/agent-instances/{quote(agent_instance_id, safe='')}/prepare-execution"
        )
        headers, http_auth = self._build_request(auth)
        logger.info(
            "[CP-CLIENT] prepare_managed_instance_execution space=%s instance=%s",
            team_id,
            agent_instance_id,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._post(
                client, url, headers=headers, http_auth=http_auth
            )
            _ = response.raise_for_status()
            try:
                data = _ExecutionRouting.model_validate(response.json())
                execute_url = data.execute_url
                if execute_url is None:
                    raise ControlPlaneEvaluationUnsupportedError(
                        "This runtime has no synchronous execute URL; select a Python agent instance that supports evaluation."
                    )
                parts = urlsplit(execute_url)
                if not parts.scheme and not self._runtime_base_url:
                    raise RuntimeError(
                        "control_plane.runtime_base_url is required for relative execution URLs."
                    )
                if (
                    not parts.path.endswith("/agents/execute")
                    or parts.query
                    or parts.fragment
                ):
                    raise ValueError("Unexpected execution URL")
                evaluate_url = urljoin(
                    self._runtime_base_url + "/",
                    execute_url.removesuffix("/agents/execute") + "/agents/evaluate",
                )
                if (
                    urlsplit(evaluate_url).scheme not in {"http", "https"}
                    or not urlsplit(evaluate_url).netloc
                ):
                    raise ValueError("Relative execution URL requires runtime_base_url")
                preparation = ManagedInstanceExecutionPreparation(
                    agent_instance_id=data.agent_instance_id,
                    runtime_id=data.runtime_id,
                    space_id=data.space_id,
                    evaluate_url=evaluate_url,
                )
                if (
                    preparation.space_id != team_id
                    or preparation.agent_instance_id != agent_instance_id
                ):
                    raise ValueError("Preparation does not match the requested target")
                return preparation
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ControlPlaneInvalidResponseError(
                    f"Malformed prepare_managed_instance_execution response: {type(exc).__name__}"
                ) from exc

    async def authorize_space(
        self, *, space_id: str, auth: OutboundAuth
    ) -> SpaceAuthorization:
        headers, http_auth = self._build_request(auth)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._post(
                client,
                f"{self._base_url}/authorize/space",
                headers=headers,
                http_auth=http_auth,
                json={"space_id": space_id, "permission": "run_evaluations"},
            )
            _ = response.raise_for_status()
            try:
                return SpaceAuthorization.model_validate(response.json())
            except (TypeError, ValueError) as exc:
                raise ControlPlaneInvalidResponseError(
                    "Malformed authorize_space response"
                ) from exc

    async def get_space(self, *, space_id: str, auth: OutboundAuth) -> SpaceDetails:
        headers, http_auth = self._build_request(auth)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._get(
                client,
                f"{self._base_url}/spaces/{quote(space_id, safe='')}",
                headers=headers,
                http_auth=http_auth,
            )
            _ = response.raise_for_status()
            try:
                return SpaceDetails.model_validate(response.json())
            except (TypeError, ValueError) as exc:
                raise ControlPlaneInvalidResponseError(
                    "Malformed get_space response"
                ) from exc

    async def list_team_application_ids(
        self,
        *,
        team_id: str,
        auth: OutboundAuth,
    ) -> frozenset[str]:
        """The Fred applications `team_id` may use, as the caller sees them.

        One call answers both halves of the hosted-app entitlement: the Control
        Plane refuses a non-member (403) and lists only applications granted to
        the team.
        """
        # Encoded: the id comes from a request path, and must name one team
        # segment, never reshape the Control Plane URL.
        url = f"{self._base_url}/teams/{quote(team_id, safe='')}/applications"
        headers, http_auth = self._build_request(auth)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._get(
                client, url, headers=headers, http_auth=http_auth
            )
            response.raise_for_status()
            try:
                return frozenset(str(item["id"]) for item in response.json()["items"])
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ControlPlaneInvalidResponseError(
                    f"Malformed list_team_applications response: {type(exc).__name__}"
                ) from exc

    async def list_team_agent_instances(
        self,
        *,
        team_id: str,
        auth: OutboundAuth,
    ) -> list[TeamAgentInstance]:
        """All pages of managed instances visible in the Weaver space."""
        url = f"{self._base_url}/spaces/{quote(team_id, safe='')}/agent-instances"
        headers, http_auth = self._build_request(auth)
        items: list[TeamAgentInstance] = []
        cursors: set[str] = set()
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                response = await self._get(
                    client, url, headers=headers, http_auth=http_auth
                )
                _ = response.raise_for_status()
                try:
                    data = _AgentInstancePage.model_validate(response.json())
                    items.extend(data.items)
                    cursor = data.next_cursor
                    if cursor is None:
                        return items
                    if not cursor or cursor in cursors:
                        raise ValueError("Invalid or repeated pagination cursor")
                    cursors.add(cursor)
                    url = (
                        f"{self._base_url}/spaces/{quote(team_id, safe='')}/agent-instances"
                        f"?after={quote(cursor, safe='')}"
                    )
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    raise ControlPlaneInvalidResponseError(
                        "Malformed list_team_agent_instances response"
                    ) from exc

    async def list_team_model_profiles(
        self,
        *,
        team_id: str,
        auth: OutboundAuth,
    ) -> list[TeamModelProfile]:
        """Disabled until Weaver model offers and model_choice are supported."""
        _ = team_id, auth
        return []
