from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException

from fred_evaluation_backend.execution.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneInvalidResponseError,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    EvaluatorErrorDetail,
    map_control_plane_error,
)
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth

logger = logging.getLogger(__name__)

# Same tuple shape as runtime_resolver._BOUNDARY_FAILURES — a plain tuple, not the
# `X | Y` union alias (`except` clauses need a class or tuple of classes).
_BOUNDARY_FAILURES = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.TransportError,
    ControlPlaneInvalidResponseError,
)


async def resolve_team_membership(
    *,
    team_id: str,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
) -> None:
    """Authorize a team-scoped action that has no execution target (datasets).

    Campaigns validate team scope for free, as a side effect of the target's
    own `prepare-execution` call. Datasets have no target, so this calls
    Control Plane's `GET /teams/{team_id}` directly with the caller's
    propagated JWT and raises the same target-neutral error vocabulary
    (`evaluator_errors`) on either a boundary failure or a non-member.
    """
    try:
        membership = await control_plane_client.get_team(team_id=team_id, auth=auth)
    except _BOUNDARY_FAILURES as exc:
        raise map_control_plane_error(
            exc,
            operation="resolve_team_membership",
            team_id=team_id,
            target=f"team={team_id}",
        ) from exc

    if not membership.is_member:
        logger.info("[TEAM-RESOLVER] team=%s caller is not a member — denying", team_id)
        raise HTTPException(
            status_code=403,
            detail=EvaluatorErrorDetail(
                code="target_forbidden",
                message="You do not have permission to use the selected team.",
            ).model_dump(),
        )
