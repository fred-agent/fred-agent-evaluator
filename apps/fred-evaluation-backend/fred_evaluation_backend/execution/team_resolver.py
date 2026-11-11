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
    """Require run_evaluations on the space stored under the legacy team_id name."""
    try:
        decision = await control_plane_client.authorize_space(
            space_id=team_id, auth=auth
        )
    except _BOUNDARY_FAILURES as exc:
        raise map_control_plane_error(
            exc,
            operation="resolve_team_membership",
            team_id=team_id,
            target=f"team={team_id}",
        ) from exc

    if not decision.allowed:
        logger.info(
            "[TEAM-RESOLVER] team=%s caller cannot run evaluations — denying", team_id
        )
        raise HTTPException(
            status_code=403,
            detail=EvaluatorErrorDetail(
                code="target_forbidden",
                message="You do not have permission to run evaluations in the selected space.",
            ).model_dump(),
        )
