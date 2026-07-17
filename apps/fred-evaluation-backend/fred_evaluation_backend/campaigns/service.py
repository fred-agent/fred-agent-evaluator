from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import uuid4

from fastapi import HTTPException

from fred_evaluation_backend.campaigns.schemas import (
    CampaignCreatedResponse,
    CreateEvaluationCampaignRequest,
    EvaluationCampaignResponse,
    EvaluationCaseListResponse,
    EvaluationCaseResponse,
    EvaluationMetricResultResponse,
    ManagedInstanceTarget,
    RunCreatedResponse,
    RunSnapshot,
    RuntimeAgentTarget,
    StructuralCheckResponse,
)
from fred_evaluation_backend.campaigns.store import EvaluationStore
from fred_evaluation_backend.datasets.schemas import DatasetCase, DatasetSummaryResponse
from fred_evaluation_backend.datasets.store import DatasetStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import dataset_not_found_error
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth
from fred_evaluation_backend.execution.runtime_resolver import resolve_managed_instance

logger = logging.getLogger(__name__)

# Server-owned default (EVAL-04): the client no longer supplies a profile.
# (The old `execution: EvaluationExecutionOptions` field — max_concurrency /
# case_timeout_seconds — was accepted by the request but never actually
# persisted or read anywhere in the old code either; removed with nothing to
# replace it. Concurrency is governed globally by `WorkerConfig.max_concurrent_cases`.)
_DEFAULT_PROFILE = "auto"
_FALLBACK_JUDGE_PROFILE_ID = "mistral-small"


def default_judge_profile_id(configured_profiles: dict[str, object]) -> str:
    """The single configured judge profile is the server-owned default.

    No request field selects it this release — `worker.judge_profiles` is
    reused as-is (no new config surface) per the task's instruction to prefer
    existing configuration over inventing new fields.
    """
    return next(iter(configured_profiles.keys()), _FALLBACK_JUDGE_PROFILE_ID)


async def create_campaign(
    request: CreateEvaluationCampaignRequest,
    *,
    created_by: str,
    store: EvaluationStore,
    dataset_store: DatasetStore,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
    judge_profile_id: str,
) -> CampaignCreatedResponse:
    dataset_row = await dataset_store.get_dataset(request.dataset_id)
    if dataset_row is None or dataset_row.team_id != request.team_id:
        # Same error for "doesn't exist" and "belongs to another team" —
        # avoids a cross-team existence leak.
        raise dataset_not_found_error()
    dataset_cases = [
        DatasetCase.model_validate(c)
        for c in json.loads(dataset_row.cases_json or "[]")
    ]

    await resolve_managed_instance(
        team_id=request.team_id,
        agent_instance_id=request.target.agent_instance_id,
        control_plane_client=control_plane_client,
        auth=auth,
    )

    campaign_id = f"eval-cmp-{uuid4().hex[:8]}"
    run_id = f"eval-run-{uuid4().hex[:8]}"
    # The task id is the campaign run's identity in the canonical task-event API.
    # It is intentionally distinct from campaign_id (a campaign may later have many
    # runs / tasks), so the frontend tracks the run via /tasks/{task_id}.
    task_id = f"eval-task-{uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).replace(microsecond=0)
    # Server-generated name (EVAL-04: no campaign-name input) — the dataset it
    # runs against plus a timestamp is enough to disambiguate in the list view.
    name = f"{dataset_row.name} — {created_at:%Y-%m-%d %H:%M}"

    await store.create_campaign(
        campaign_id=campaign_id,
        run_id=run_id,
        task_id=task_id,
        name=name,
        team_id=request.team_id,
        created_by=created_by,
        target_kind="managed_instance",
        target_runtime_id=None,
        target_agent_id=None,
        target_instance_id=request.target.agent_instance_id,
        dataset_id=dataset_row.dataset_id,
        dataset_name=None,
        dataset_version=None,
        profile=_DEFAULT_PROFILE,
        judge_profile_id=judge_profile_id,
        total_cases=len(dataset_cases),
        custom_metrics_json=None,
    )

    for case in dataset_cases:
        await store.create_case(
            case_id=f"case-{uuid4().hex[:8]}",
            campaign_id=campaign_id,
            run_id=run_id,
            external_id=case.external_id,
            input=case.input,
            expected_output=case.expected_output,
        )

    return CampaignCreatedResponse(
        campaign_id=campaign_id,
        run_id=run_id,
        task_id=task_id,
        state="pending",
    )


async def start_run(
    *,
    evaluation_id: str,
    team_id: str,
    target: ManagedInstanceTarget,
    created_by: str,
    store: EvaluationStore,
    dataset_store: DatasetStore,
    control_plane_client: ControlPlaneClient,
    auth: OutboundAuth,
    profile: str,
    judge_profile_id: str,
) -> RunCreatedResponse:
    """EVAL-05: start one Run of an existing Evaluation against a chosen target.

    Unlike `create_campaign`, this does not create an Evaluation — it references one that
    already exists, and is repeatable (each call is an independent Run). The Run freezes a
    RunSnapshot at Start: the Evaluation's immutability pins the cases, the snapshot pins
    the target/policy actually used (RFC §9.5).
    """
    evaluation = await dataset_store.get_dataset(evaluation_id)
    if evaluation is None or evaluation.team_id != team_id:
        # Same error for "doesn't exist" and "belongs to another team" — no cross-team leak.
        raise dataset_not_found_error()
    cases = [
        DatasetCase.model_validate(c)
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

    snapshot = RunSnapshot(
        evaluation_name=evaluation.name,
        evaluation_version=evaluation.version,
        target=target,
        profile=profile,
        judge_profile_id=judge_profile_id,
    )

    await store.create_run(
        run_id=run_id,
        evaluation_id=evaluation_id,
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


def _dataset_summary(row) -> DatasetSummaryResponse | None:
    if row is None:
        return None
    cases = json.loads(row.cases_json) if row.cases_json else []
    return DatasetSummaryResponse(
        dataset_id=row.dataset_id,
        name=row.name,
        version=row.version,
        team_id=row.team_id,
        origin=row.origin,
        completeness=row.completeness,
        case_count=len(cases),
        created_at=row.created_at,
    )


def _campaign_row_to_response(row, dataset_row) -> EvaluationCampaignResponse:
    if row.target_kind == "runtime_agent":
        target = RuntimeAgentTarget(
            kind="runtime_agent",
            runtime_id=row.target_runtime_id or "",
            agent_id=row.target_agent_id or "",
        )
    else:
        target = ManagedInstanceTarget(
            kind="managed_instance",
            agent_instance_id=row.target_instance_id or "",
        )

    return EvaluationCampaignResponse(
        campaign_id=row.campaign_id,
        run_id=row.run_id,
        task_id=row.task_id,
        name=row.name,
        team_id=row.team_id,
        created_by=row.created_by,
        target=target,
        dataset=_dataset_summary(dataset_row),
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
        metric_averages=json.loads(row.metric_averages_json)
        if row.metric_averages_json
        else None,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


async def get_campaign(
    campaign_id: str,
    *,
    store: EvaluationStore,
    dataset_store: DatasetStore,
) -> EvaluationCampaignResponse:
    row = await store.get_campaign(campaign_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Campaign '{campaign_id}' not found."
        )
    dataset_row = (
        await dataset_store.get_dataset(row.dataset_id) if row.dataset_id else None
    )
    return _campaign_row_to_response(row, dataset_row)


async def list_campaigns(
    team_id: str,
    *,
    store: EvaluationStore,
    dataset_store: DatasetStore,
) -> list[EvaluationCampaignResponse]:
    rows = await store.list_campaigns_by_team(team_id)
    dataset_ids = [row.dataset_id for row in rows if row.dataset_id]
    datasets_by_id = await dataset_store.get_datasets_by_ids(dataset_ids)
    return [
        _campaign_row_to_response(
            row, datasets_by_id.get(row.dataset_id) if row.dataset_id else None
        )
        for row in rows
    ]


async def cancel_campaign(
    campaign_id: str,
    *,
    store: EvaluationStore,
) -> None:
    row = await store.get_campaign(campaign_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Campaign '{campaign_id}' not found."
        )
    if row.operational_state in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Campaign '{campaign_id}' is already in terminal state '{row.operational_state}'.",
        )
    await store.update_campaign_state(campaign_id, "cancelled")


async def list_cases(
    campaign_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
    store: EvaluationStore,
) -> EvaluationCaseListResponse:
    rows = await store.list_cases_by_campaign(campaign_id, offset=offset, limit=limit)
    cases = []
    for row in rows:
        metrics = await store.list_metrics_by_case(row.case_id)
        cases.append(
            EvaluationCaseResponse(
                case_id=row.case_id,
                campaign_id=row.campaign_id,
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
                else __import__("json").loads(row.scoring_errors_json),
                metrics=[
                    EvaluationMetricResultResponse(
                        name=m.name,
                        provider=m.provider,
                        score=float(m.score) if m.score is not None else None,
                        threshold=float(m.threshold)
                        if m.threshold is not None
                        else None,
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
                        __import__("json").loads(row.structural_checks_json)
                        if row.structural_checks_json
                        else []
                    )
                ],
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
        )
    return EvaluationCaseListResponse(cases=cases, total=len(cases))


async def delete_campaign(
    campaign_id: str,
    *,
    store: EvaluationStore,
) -> None:
    row = await store.get_campaign(campaign_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Campaign '{campaign_id}' not found."
        )
    if row.operational_state == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Campaign '{campaign_id}' is currently running and cannot be deleted.",
        )
    await store.delete_campaign(campaign_id)
