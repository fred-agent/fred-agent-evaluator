from __future__ import annotations

from datetime import datetime, timezone

from fred_core.tasks import (
    EvaluationDetail,
    EvaluationTaskEvent,
    TaskListResponse,
    TaskState,
    TaskSummary,
    TaskTarget,
)

from fred_evaluation_backend.campaigns.models import EvaluationCampaignRow

# ── Mapping: evaluation campaign row → canonical task shape ───────────────────

# The campaign's `operational_state` predates the task state machine; map it onto
# the canonical six-state `TaskState`. "completed" is a terminal success.
_STATE_MAP: dict[str, TaskState] = {
    "pending": TaskState.pending,
    "running": TaskState.running,
    "completed": TaskState.succeeded,
    "succeeded": TaskState.succeeded,
    "failed": TaskState.failed,
    "cancelled": TaskState.cancelled,
    "cancelling": TaskState.cancelling,
}


def map_state(operational_state: str) -> TaskState:
    return _STATE_MAP.get(operational_state, TaskState.pending)


def _progress(row: EvaluationCampaignRow) -> float | None:
    return (row.completed_cases / row.total_cases) if row.total_cases else None


def _target(row: EvaluationCampaignRow) -> TaskTarget:
    return TaskTarget(type="evaluation_campaign", id=row.campaign_id, label=row.name)


def campaign_to_summary(row: EvaluationCampaignRow) -> TaskSummary:
    """One campaign row → a current-state task snapshot (GET /tasks)."""
    return TaskSummary(
        task_id=row.task_id or row.campaign_id,
        kind="evaluation",
        state=map_state(row.operational_state),
        progress=_progress(row),
        step=None,
        error=None,
        target=_target(row),
        created_by=row.created_by,
        team_id=row.team_id,
        created_at=row.created_at,
        updated_at=row.completed_at or row.started_at or row.created_at,
    )


def campaign_to_event(row: EvaluationCampaignRow, seq: int) -> EvaluationTaskEvent:
    """One campaign row → a canonical evaluation task event (SSE / latest)."""
    return EvaluationTaskEvent(
        task_id=row.task_id or row.campaign_id,
        state=map_state(row.operational_state),
        seq=seq,
        timestamp=datetime.now(timezone.utc),
        progress=_progress(row),
        step=None,
        error=None,
        target=_target(row),
        owner=row.created_by,
        detail=EvaluationDetail(
            campaign_id=row.campaign_id,
            completed=row.completed_cases,
            total=row.total_cases,
            passed=row.passed_cases,
            failed=row.failed_cases,
            execution_errors=row.execution_error_cases,
            scoring_errors=row.scoring_error_cases,
        ),
    )


__all__ = [
    "EvaluationDetail",
    "EvaluationTaskEvent",
    "TaskListResponse",
    "TaskSummary",
    "TaskState",
    "TaskTarget",
    "map_state",
    "campaign_to_summary",
    "campaign_to_event",
]
