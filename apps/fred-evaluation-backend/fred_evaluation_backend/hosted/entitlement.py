"""Control Plane entitlement gate for the `evaluation` Fred application.

Fred's application gateway proxies `/app-services/evaluation/teams/<team_id>/...`
to this API with the `/app-services/evaluation` prefix stripped and the caller's
`Authorization` header forwarded untouched. It authorizes nothing beyond the
app id being installed, so every hosted route depends on `require_entitled`:
the Control Plane is asked whether the caller's team may use this application,
and any answer other than a clear yes is a refusal.
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import Depends, Request
from fred_core import KeycloakUser, get_config, get_current_user

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

logger = logging.getLogger(__name__)

APP_ID = "evaluation"

_BOUNDARY_FAILURES = (
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
    user: Annotated[KeycloakUser, Depends(get_current_user)],
    cp_client: Annotated[ControlPlaneClient, Depends(get_control_plane_client)],
) -> OutboundAuth:
    """Admit the request only if `team_id` is granted this application.

    One Control Plane call answers both halves, since grants go from team to
    application: a non-member is refused outright (403 -> `target_forbidden`),
    and a member whose team was never granted the application does not see it
    listed. An unreachable or incoherent Control Plane is a refusal too, never
    an admission. Returns the caller's outbound identity for the route to reuse.
    """
    configuration = request.app.dependency_overrides.get(get_config, get_config)()
    auth = resolve_interactive_auth(
        request, user_security_enabled=configuration.security.user.enabled
    )
    try:
        granted = await cp_client.list_team_application_ids(team_id=team_id, auth=auth)
    except _BOUNDARY_FAILURES as exc:
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
