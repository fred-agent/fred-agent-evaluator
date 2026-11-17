"""Control Plane entitlement gate for the `evaluation` Fred application.

Fred's application gateway proxies `/app-services/evaluation/teams/<team_id>/...`
to this API with the `/app-services/evaluation` prefix stripped and the caller's
`Authorization` header forwarded untouched. The proxy checks the registered
application, space offer and entry permission. Each hosted route independently
checks its business permission; an application offer never grants evaluation rights.
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import Depends, Request
from fred_core import KeycloakUser, get_config
from fred_core.security.oidc import authenticate_request
from fred_core.common.team_id import PERSONAL_TEAM_ALIAS

from fred_evaluation_backend.execution.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneInvalidResponseError,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    application_not_granted_error,
    map_control_plane_error,
)
from fred_evaluation_backend.execution.outbound_auth import (
    OutboundAuth,
    resolve_interactive_auth,
)
from fred_evaluation_backend.execution.team_resolver import resolve_team_membership

logger = logging.getLogger(__name__)

APP_ID = "evaluation"

# The Control Plane boundary failures a hosted route reclassifies (403 target_forbidden,
# 503 control_plane_unavailable, 502 control_plane_invalid_response, ...).
CONTROL_PLANE_FAILURES = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.TransportError,
    ControlPlaneInvalidResponseError,
)


def get_control_plane_client(request: Request) -> ControlPlaneClient:
    return request.app.state.control_plane_client


async def require_entitled(
    team_id: str,
    request: Request,
    user: Annotated[KeycloakUser, Depends(authenticate_request)],
    cp_client: Annotated[ControlPlaneClient, Depends(get_control_plane_client)],
) -> OutboundAuth:
    """Admit the request only if `team_id` is granted this application.

    Weaver returns enabled applications effectively offered to this space.
    Unreachable or incoherent responses fail closed. The caller identity is
    reused by the business permission gate and route.
    """
    # Hosted applications support organization/team/project UUIDs, not personal
    # spaces. Weaver enforces space kinds; reject the historical alias locally.
    if team_id == PERSONAL_TEAM_ALIAS:
        raise application_not_granted_error()

    configuration = request.app.dependency_overrides.get(get_config, get_config)()
    auth = resolve_interactive_auth(
        request, user_security_enabled=configuration.security.user.enabled
    )
    try:
        granted = await cp_client.list_team_application_ids(team_id=team_id, auth=auth)
    except CONTROL_PLANE_FAILURES as exc:
        raise map_control_plane_error(
            exc,
            operation="require_entitled",
            team_id=team_id,
            target=f"application={APP_ID}",
        ) from exc
    if APP_ID not in granted:
        logger.info(
            "[HOSTED] team=%s user=%s is not granted application %s — denying",
            team_id,
            user.uid,
            APP_ID,
        )
        raise application_not_granted_error()
    return auth


async def require_evaluation_access(
    team_id: str,
    auth: Annotated[OutboundAuth, Depends(require_entitled)],
    cp_client: Annotated[ControlPlaneClient, Depends(get_control_plane_client)],
) -> OutboundAuth:
    await resolve_team_membership(
        team_id=team_id, control_plane_client=cp_client, auth=auth
    )
    return auth
