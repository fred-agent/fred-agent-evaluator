"""Team authorization for `/evaluation/v1` routes that name a run, a task or an
evaluation by id.

Those ids are global, so authentication alone would let any caller read,
cancel or delete another team's run by knowing its id. Each helper loads the
resource first, then asks the Control Plane whether the caller belongs to the
resource's *own* team — never to a team the caller names — exactly as
`evaluations.service.delete_evaluation` already does.

The team-scoped application surface (`hosted/`) has its own gates and does not
use these.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fred_core import get_config

from fred_evaluation_backend.evaluations.models import EvaluationRow
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import (
    evaluation_not_found_error,
)
from fred_evaluation_backend.execution.outbound_auth import resolve_interactive_auth
from fred_evaluation_backend.execution.team_resolver import resolve_team_membership
from fred_evaluation_backend.runs.models import EvaluationRunRow
from fred_evaluation_backend.runs.store import RunStore


async def require_team_member(
    request: Request, team_id: str, *, cp_client: ControlPlaneClient
) -> None:
    """403 unless the caller belongs to `team_id` (Control Plane, caller's token)."""
    configuration = request.app.dependency_overrides.get(get_config, get_config)()
    await resolve_team_membership(
        team_id=team_id,
        control_plane_client=cp_client,
        auth=resolve_interactive_auth(
            request, user_security_enabled=configuration.security.user.enabled
        ),
    )


async def authorize_run(
    request: Request,
    run_id: str,
    *,
    store: RunStore,
    cp_client: ControlPlaneClient,
) -> EvaluationRunRow:
    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    await require_team_member(request, row.team_id, cp_client=cp_client)
    return row


async def authorize_task(
    request: Request,
    task_id: str,
    *,
    store: RunStore,
    cp_client: ControlPlaneClient,
) -> EvaluationRunRow:
    row = await store.get_run_by_task_id(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    await require_team_member(request, row.team_id, cp_client=cp_client)
    return row


async def authorize_evaluation(
    request: Request,
    evaluation_id: str,
    *,
    evaluation_store: EvaluationStore,
    cp_client: ControlPlaneClient,
) -> EvaluationRow:
    row = await evaluation_store.get_evaluation(evaluation_id)
    if row is None:
        raise evaluation_not_found_error()
    await require_team_member(request, row.team_id, cp_client=cp_client)
    return row
