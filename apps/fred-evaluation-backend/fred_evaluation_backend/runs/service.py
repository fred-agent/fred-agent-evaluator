from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import uuid4

from fastapi import HTTPException

from fred_evaluation_backend.evaluations.schemas import EvaluationCase
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import (
    evaluation_not_found_error,
)
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth
from fred_evaluation_backend.execution.runtime_resolver import resolve_managed_instance
from fred_evaluation_backend.runs.schemas import (
    EvaluationCaseListResponse,
    EvaluationCaseResponse,
    EvaluationMetricResultResponse,
    EvaluationRun,
    ManagedInstanceTarget,
    RunCreatedResponse,
    RunReportEvaluation,
    RunReportResponse,
    RunSnapshot,
    StoredRunAnalysis,
    StructuralCheckResponse,
)
from fred_evaluation_backend.runs.store import RunStore

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE = "auto"
_FALLBACK_JUDGE_PROFILE_ID = "mistral-small"


def default_judge_profile_id(configured_profiles: dict[str, object]) -> str:
    return next(iter(configured_profiles.keys()), _FALLBACK_JUDGE_PROFILE_ID)


async def start_run(
    *,
    evaluation_id: str,
    team_id: str,
    target: ManagedInstanceTarget,
    created_by: str,
    store: RunStore,
    evaluation_store: EvaluationStore,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
    profile: str,
    judge_profile_id: str,
    max_concurrency: int,
) -> RunCreatedResponse:
    evaluation = await evaluation_store.get_evaluation(evaluation_id)
    if evaluation is None or evaluation.team_id != team_id:
        raise evaluation_not_found_error()
    cases = [
        EvaluationCase.model_validate(c)
        for c in json.loads(evaluation.cases_json or "[]")
    ]

    await resolve_managed_instance(
        team_id=team_id,
        agent_instance_id=target.agent_instance_id,
        control_plane_client=control_plane_client,
        auth=auth,
    )

    run_id = f"eval-run-{uuid4().hex[:8]}"
    task_id = f"eval-task-{uuid4().hex[:8]}"

    # Frozen with the rest of the run's parameters. Concurrency is a property of
    # THIS run against THIS target — a later config change must not retroactively
    # describe how a past run was paced.
    snapshot = RunSnapshot(
        evaluation_name=evaluation.name,
        evaluation_version=evaluation.version,
        target=target,
        profile=profile,
        judge_profile_id=judge_profile_id,
        execution={"max_concurrency": max_concurrency},
    )

    await store.create_run(
        run_id=run_id,
        evaluation_id=evaluation_id,
        team_id=team_id,
        created_by=created_by,
        task_id=task_id,
        target_kind="managed_instance",
        target_runtime_id=None,
        target_agent_id=None,
        target_instance_id=target.agent_instance_id,
        profile=profile,
        judge_profile_id=judge_profile_id,
        total_cases=len(cases),
        custom_metrics_json=None,
        snapshot_json=snapshot.model_dump_json(),
    )

    for case in cases:
        await store.create_case(
            case_id=f"case-{uuid4().hex[:8]}",
            run_id=run_id,
            external_id=case.external_id,
            input=case.input,
            expected_output=case.expected_output,
        )

    return RunCreatedResponse(
        run_id=run_id,
        evaluation_id=evaluation_id,
        task_id=task_id,
        state="pending",
    )


def _run_to_response(row) -> EvaluationRun:
    return EvaluationRun(
        run_id=row.run_id,
        evaluation_id=row.evaluation_id,
        task_id=row.task_id,
        target=ManagedInstanceTarget(
            kind="managed_instance", agent_instance_id=row.target_instance_id
        ),
        profile=row.profile,
        judge_profile_id=row.judge_profile_id,
        operational_state=row.operational_state,
        verdict=row.verdict,
        total_cases=row.total_cases,
        completed_cases=row.completed_cases,
        passed_cases=row.passed_cases,
        failed_cases=row.failed_cases,
        execution_error_cases=row.execution_error_cases,
        scoring_error_cases=row.scoring_error_cases,
        snapshot=RunSnapshot.model_validate_json(row.snapshot_json),
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


async def get_run(run_id: str, *, store: RunStore) -> EvaluationRun:
    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return _run_to_response(row)


async def list_runs(evaluation_id: str, *, store: RunStore) -> list[EvaluationRun]:
    rows = await store.list_runs_by_evaluation(evaluation_id)
    return [_run_to_response(row) for row in rows]


def _case_to_response(row, metrics) -> EvaluationCaseResponse:
    return EvaluationCaseResponse(
        case_id=row.case_id,
        run_id=row.run_id,
        external_id=row.external_id,
        status=row.status,
        outcome=row.outcome,
        verdict=row.verdict,
        input=row.input,
        expected_output=row.expected_output,
        actual_output=row.actual_output,
        profile=row.profile,
        latency_ms=row.latency_ms,
        execution_error=row.execution_error,
        scoring_errors=[]
        if not row.scoring_errors_json
        else json.loads(row.scoring_errors_json),
        metrics=[
            EvaluationMetricResultResponse(
                name=m.name,
                provider=m.provider,
                score=float(m.score) if m.score is not None else None,
                threshold=float(m.threshold) if m.threshold is not None else None,
                verdict=cast(
                    Literal["passed", "failed", "skipped", "error"], m.verdict
                ),
                explanation=m.explanation,
                error=m.error,
            )
            for m in metrics
        ],
        structural_checks=[
            StructuralCheckResponse(**c)
            for c in (
                json.loads(row.structural_checks_json)
                if row.structural_checks_json
                else []
            )
        ],
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


async def list_run_cases(
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
    store: RunStore,
) -> EvaluationCaseListResponse:
    rows = await store.list_cases_by_run(run_id, offset=offset, limit=limit)
    cases = [
        _case_to_response(row, await store.list_metrics_by_case(row.case_id))
        for row in rows
    ]
    return EvaluationCaseListResponse(cases=cases, total=len(cases))


async def get_run_case(
    run_id: str,
    case_id: str,
    *,
    store: RunStore,
) -> EvaluationCaseResponse:
    rows = await store.list_cases_by_run(run_id, limit=10000)
    row = next((c for c in rows if c.case_id == case_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    return _case_to_response(row, await store.list_metrics_by_case(case_id))


async def cancel_run(
    run_id: str,
    *,
    store: RunStore,
) -> None:
    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    if row.operational_state in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run_id}' is already in terminal state '{row.operational_state}'.",
        )
    await store.update_run_state(run_id, "cancelled")


async def delete_run(
    run_id: str,
    *,
    store: RunStore,
) -> None:
    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    if row.operational_state == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run_id}' is currently running and cannot be deleted.",
        )
    await store.delete_run(run_id)


# A run holds at most as many cases as its evaluation (capped at 200 on creation),
# so a single unpaginated read is bounded; the ceiling is a guard, not a page size.
_REPORT_CASE_LIMIT = 10_000


async def build_run_report(
    run_id: str,
    *,
    store: RunStore,
    evaluation_store: EvaluationStore,
    control_plane_client: ControlPlaneClient | None = None,
    auth: OutboundAuth | None = None,
) -> RunReportResponse:
    """Assemble the complete, self-contained JSON record of one run."""
    run_row = await store.get_run(run_id)
    if run_row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    evaluation_row = await evaluation_store.get_evaluation(run_row.evaluation_id)
    if evaluation_row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Evaluation '{run_row.evaluation_id}' backing run '{run_id}' "
                "no longer exists."
            ),
        )

    # Best-effort: a report that loses its team name is degraded, one that 500s
    # because the Control Plane hiccuped is useless. Never fail the archive on it.
    team_name: str | None = None
    if control_plane_client is not None and auth is not None:
        try:
            membership = await control_plane_client.get_team(
                team_id=evaluation_row.team_id, auth=auth
            )
            team_name = membership.name
        except Exception:
            logger.warning(
                "[REPORT] could not resolve team name for %s", evaluation_row.team_id
            )

    case_rows = await store.list_cases_by_run(run_id, limit=_REPORT_CASE_LIMIT)
    cases = [
        _case_to_response(row, await store.list_metrics_by_case(row.case_id))
        for row in case_rows
    ]

    # Stored wrapped as {"analysis": {...}} by the analyze endpoint, not as a bare
    # RunAnalysisResult — unwrap it here rather than trusting the column shape.
    analysis = (
        StoredRunAnalysis.model_validate_json(run_row.analysis_json).analysis
        if run_row.analysis_json
        else None
    )

    return RunReportResponse(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        evaluation=RunReportEvaluation(
            evaluation_id=evaluation_row.evaluation_id,
            name=evaluation_row.name,
            version=evaluation_row.version,
            team_id=evaluation_row.team_id,
            team_name=team_name,
            author=evaluation_row.author,
            created_by=evaluation_row.created_by,
            origin=evaluation_row.origin,
            completeness=evaluation_row.completeness,
            created_at=evaluation_row.created_at,
        ),
        run=_run_to_response(run_row),
        metric_averages=(
            json.loads(run_row.metric_averages_json)
            if run_row.metric_averages_json
            else None
        ),
        analysis=analysis,
        cases=cases,
    )
