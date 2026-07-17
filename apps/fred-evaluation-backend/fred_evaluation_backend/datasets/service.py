from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fred_evaluation_backend.datasets.schemas import (
    CreateEvaluationRequest,
    Evaluation,
    EvaluationDetailResponse,
    EvaluationListResponse,
    EvaluationSummaryResponse,
)
from fred_evaluation_backend.datasets.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth
from fred_evaluation_backend.execution.team_resolver import resolve_team_membership

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
    name = request.name

    # EVAL-05: re-importing the same name in the same team creates the next version,
    # which becomes current. Each version is its own row (its own dataset_id); the
    # grouped list keys on `name`, and current = the highest version (RFC §8.5, lecture A).
    next_number = await store.get_latest_version_number(request.team_id, name) + 1
    version = f"v{next_number}"

    # Reuse the frozen domain model's own completeness derivation (single
    # source of truth — see EvaluationDataset._derive_completeness) rather
    # than re-implementing the "all cases have expected_output" rule here.
    domain_evaluation = Evaluation(
        evaluation_id=evaluation_id,
        name=name,
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
        name=name,
        version=version,
        team_id=request.team_id,
        created_by=created_by,
        origin=request.origin,
        completeness=domain_evaluation.completeness.value,
        cases_json=_cases_to_json(domain_evaluation),
    )

    return EvaluationDetailResponse(
        evaluation_id=evaluation_id,
        name=name,
        version=version,
        author=created_by,
        team_id=request.team_id,
        origin=request.origin,
        completeness=domain_evaluation.completeness,
        case_count=len(request.cases),
        created_at=created_at,
        cases=request.cases,
    )


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
        evaluation_id=row.dataset_id,
        name=row.name,
        version=row.version,
        author=row.created_by,
        team_id=row.team_id,
        origin=row.origin,
        completeness=row.completeness,
        case_count=len(cases),
        created_at=row.created_at,
    )


def _cases_to_json(domain_evaluation: Evaluation) -> str:
    return json.dumps([c.model_dump() for c in domain_evaluation.cases])


create_dataset = create_evaluation
list_datasets = list_evaluations
