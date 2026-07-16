from __future__ import annotations

import logging

import httpx

from fred_evaluation_backend.execution.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneInvalidResponseError,
    ManagedInstanceExecutionPreparation,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    map_control_plane_error,
)
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth

logger = logging.getLogger(__name__)

# Known external-boundary failures only. A local/programming/configuration
# defect (RuntimeError, KeyError from our own code, etc.) must propagate as
# itself — never be relabelled as a Control Plane failure.
_BOUNDARY_FAILURES = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.TransportError,
    ControlPlaneInvalidResponseError,
)


async def resolve_managed_instance(
    *,
    team_id: str,
    agent_instance_id: str,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
) -> ManagedInstanceExecutionPreparation:
    """
    Resolve a managed_instance target into an execution preparation.

    Only known Control Plane boundary failures are classified (never a blanket
    422) — see `evaluator_errors.map_control_plane_error`. Anything else
    propagates as a real server error.
    """
    try:
        return await control_plane_client.prepare_managed_instance_execution(
            team_id=team_id,
            agent_instance_id=agent_instance_id,
            auth=auth,
        )
    except _BOUNDARY_FAILURES as exc:
        raise map_control_plane_error(
            exc,
            operation="resolve_managed_instance",
            team_id=team_id,
            target=f"agent_instance={agent_instance_id}",
        ) from exc
