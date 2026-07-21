from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import HTTPException

from fred_evaluation_backend.evaluations.schemas import (
    CreateEvaluationRequest,
    Evaluation,
    EvaluationDetailResponse,
    EvaluationListResponse,
    EvaluationSummaryResponse,
)
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth
from fred_evaluation_backend.execution.team_resolver import resolve_team_membership

if TYPE_CHECKING:  # `runs` imports `evaluations`; keep the runtime edge one-way.
    from fred_evaluation_backend.runs.store import RunStore

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def create_evaluation(
    request: CreateEvaluationRequest,
    *,
    created_by: str,
    store: EvaluationStore,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
) -> EvaluationDetailResponse:
    await resolve_team_membership(
        team_id=request.team_id,
        control_plane_client=control_plane_client,
        auth=auth,
    )

    created_at = _utcnow()
    evaluation_id = f"eval-{uuid4().hex[:8]}"
    version = await _resolve_version(request, store=store)

    domain_evaluation = Evaluation(
        evaluation_id=evaluation_id,
        name=request.name,
        version=version,
        team_id=request.team_id,
        created_by=created_by,
        origin=request.origin,
        source_question_set_id=None,
        cases=request.cases,
        created_at=created_at,
    )

    await store.create_evaluation(
        evaluation_id=evaluation_id,
        name=request.name,
        version=version,
        team_id=request.team_id,
        created_by=created_by,
        author=request.author,
        origin=request.origin,
        completeness=domain_evaluation.completeness.value,
        cases_json=_cases_to_json(domain_evaluation),
    )

    return EvaluationDetailResponse(
        evaluation_id=evaluation_id,
        name=request.name,
        version=version,
        author=request.author,
        created_by=created_by,
        team_id=request.team_id,
        origin=request.origin,
        completeness=domain_evaluation.completeness,
        case_count=len(request.cases),
        created_at=created_at,
        cases=request.cases,
    )


async def _resolve_version(
    request: CreateEvaluationRequest,
    *,
    store: EvaluationStore,
) -> str:
    """A declared version wins and must be unique; otherwise the server assigns one.

    `get_latest_version_number` only counts server-style `v<n>` versions, so a
    declared "1.0.0" never perturbs the auto-increment sequence.
    """
    if request.version is None:
        next_number = (
            await store.get_latest_version_number(request.team_id, request.name) + 1
        )
        return f"v{next_number}"

    if await store.version_exists(request.team_id, request.name, request.version):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Evaluation '{request.name}' version '{request.version}' already "
                f"exists for team '{request.team_id}'."
            ),
        )
    return request.version


async def list_evaluations(
    team_id: str,
    *,
    store: EvaluationStore,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
) -> EvaluationListResponse:
    await resolve_team_membership(
        team_id=team_id,
        control_plane_client=control_plane_client,
        auth=auth,
    )
    rows = await store.list_evaluations_by_team(team_id)
    evaluations = [_row_to_summary(row) for row in rows]
    return EvaluationListResponse(evaluations=evaluations, total=len(evaluations))


def _row_to_summary(row) -> EvaluationSummaryResponse:
    cases = json.loads(row.cases_json) if row.cases_json else []
    return EvaluationSummaryResponse(
        evaluation_id=row.evaluation_id,
        name=row.name,
        version=row.version,
        author=row.author,
        created_by=row.created_by,
        team_id=row.team_id,
        origin=row.origin,
        completeness=row.completeness,
        case_count=len(cases),
        created_at=row.created_at,
    )


def _cases_to_json(domain_evaluation: Evaluation) -> str:
    return json.dumps([c.model_dump() for c in domain_evaluation.cases])


async def delete_evaluation(
    evaluation_id: str,
    *,
    store: EvaluationStore,
    run_store: RunStore,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
) -> None:
    """Delete an evaluation and every run that executed it.

    Cascading is explicit: `evaluation_run.evaluation_id` is a plain foreign key
    with no ON DELETE, so the runs have to go first or the delete would fail on
    integrity. `delete_run` already clears each run's cases, metrics, events and
    export deliveries.
    """
    row = await store.get_evaluation(evaluation_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Evaluation '{evaluation_id}' not found."
        )

    # Authorised against the evaluation's own team, as create/list are — the
    # caller does not get to name the team they are deleting from.
    await resolve_team_membership(
        team_id=row.team_id,
        control_plane_client=control_plane_client,
        auth=auth,
    )

    runs = await run_store.list_runs_by_evaluation(evaluation_id)
    running = [r.run_id for r in runs if r.operational_state == "running"]
    if running:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Evaluation '{evaluation_id}' has {len(running)} run(s) currently "
                "running and cannot be deleted."
            ),
        )

    for run in runs:
        _ = await run_store.delete_run(run.run_id)
    _ = await store.delete_evaluation(evaluation_id)
