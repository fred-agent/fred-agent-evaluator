from __future__ import annotations

import logging

import httpx
from fred_core import M2MBearerAuth, M2MTokenProvider
from pydantic import BaseModel

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


# RUNTIME-07 rev.2: prepare-execution no longer returns a signed execution_grant.
# Authorization happens at the runtime pod via the caller's JWT + OpenFGA. These
# preparations therefore only carry routing (evaluate_url) and the team scope.
#
# EVAL-04: `runtime_agent` is no longer an accepted target at run
# creation (creation is managed-instance-only). This preparation type and
# the client method below are kept because the worker (workers/workflow.py,
# workers/runner.py) still executes legacy rows created before EVAL-04 with
# `target_kind == "runtime_agent"` — removing them would break in-flight
# execution of pre-existing work, not just tidy up unused code.
class RuntimeAgentExecutionPreparation(BaseModel):
    runtime_id: str
    agent_id: str
    team_id: str
    evaluate_url: str


class ManagedInstanceExecutionPreparation(BaseModel):
    agent_instance_id: str
    runtime_id: str
    team_id: str
    evaluate_url: str


class TeamMembership(BaseModel):
    """Whether the caller belongs to a team — no execution target involved.

    Used for evaluation-catalog endpoints, which (unlike runs) have no agent/runtime
    target whose own `prepare-execution` call already enforces team scope.
    """

    team_id: str
    is_member: bool


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
    ) -> httpx.Response:
        # httpx's `post()` convenience method doesn't accept `auth=None` (only its
        # lower-level `request()` does) — omit the kwarg instead, which is
        # equivalent here since these clients never carry a default auth.
        if http_auth is not None:
            return await client.post(url, headers=headers, auth=http_auth)
        return await client.post(url, headers=headers)

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

    async def prepare_runtime_agent_execution(
        self,
        *,
        team_id: str,
        runtime_id: str,
        agent_id: str,
        auth: OutboundAuth,
    ) -> RuntimeAgentExecutionPreparation:
        url = (
            f"{self._base_url}/teams/{team_id}"
            f"/runtimes/{runtime_id}/agents/{agent_id}/prepare-execution"
        )
        headers, http_auth = self._build_request(auth)
        logger.info(
            "[CP-CLIENT] prepare_runtime_agent_execution team=%s runtime=%s agent=%s",
            team_id,
            runtime_id,
            agent_id,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._post(
                client, url, headers=headers, http_auth=http_auth
            )
            response.raise_for_status()
            try:
                data = response.json()
                evaluate_url = data.get("evaluate_url", "")
                if evaluate_url.startswith("/") and self._runtime_base_url:
                    data = {
                        **data,
                        "evaluate_url": f"{self._runtime_base_url}{evaluate_url}",
                    }
                return RuntimeAgentExecutionPreparation.model_validate(data)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ControlPlaneInvalidResponseError(
                    f"Malformed prepare_runtime_agent_execution response: {type(exc).__name__}"
                ) from exc

    async def prepare_managed_instance_execution(
        self,
        *,
        team_id: str,
        agent_instance_id: str,
        auth: OutboundAuth,
    ) -> ManagedInstanceExecutionPreparation:
        url = (
            f"{self._base_url}/teams/{team_id}"
            f"/agent-instances/{agent_instance_id}/prepare-execution"
        )
        headers, http_auth = self._build_request(auth)
        logger.info(
            "[CP-CLIENT] prepare_managed_instance_execution team=%s instance=%s",
            team_id,
            agent_instance_id,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._post(
                client, url, headers=headers, http_auth=http_auth
            )
            response.raise_for_status()
            try:
                data = response.json()
                execute_url = data["execute_url"]
                if execute_url.startswith("/") and self._runtime_base_url:
                    execute_url = f"{self._runtime_base_url}{execute_url}"
                evaluate_url = execute_url.replace(
                    "/agents/execute", "/agents/evaluate"
                )
                return ManagedInstanceExecutionPreparation(
                    agent_instance_id=agent_instance_id,
                    runtime_id=data["runtime_id"],
                    team_id=str(data["team_id"]),
                    evaluate_url=evaluate_url,
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ControlPlaneInvalidResponseError(
                    f"Malformed prepare_managed_instance_execution response: {type(exc).__name__}"
                ) from exc

    async def get_team(
        self,
        *,
        team_id: str,
        auth: OutboundAuth,
    ) -> TeamMembership:
        """Check whether the caller belongs to `team_id` — no execution target.

        Reuses the caller's propagated JWT the same way `prepare_*_execution`
        does; this is the evaluation-catalog domain's team-scoping check, since evaluations
        have no agent/runtime target to piggyback authorization on.
        """
        url = f"{self._base_url}/teams/{team_id}"
        headers, http_auth = self._build_request(auth)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await self._get(
                client, url, headers=headers, http_auth=http_auth
            )
            response.raise_for_status()
            try:
                data = response.json()
                return TeamMembership(
                    team_id=team_id, is_member=bool(data["is_member"])
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ControlPlaneInvalidResponseError(
                    f"Malformed get_team response: {type(exc).__name__}"
                ) from exc
