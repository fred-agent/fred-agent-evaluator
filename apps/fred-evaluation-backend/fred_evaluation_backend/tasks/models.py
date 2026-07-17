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

from fred_evaluation_backend.campaigns.models import EvaluationRunRow
from fred_evaluation_backend.campaigns.schemas import RunSnapshot

# ── Mapping: evaluation run row → canonical task shape ────────────────────────

# The run's `operational_state` predates the task state machine; map it onto
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


def _progress(row: EvaluationRunRow) -> float | None:
    return (row.completed_cases / row.total_cases) if row.total_cases else None


def _target(row: EvaluationRunRow) -> TaskTarget:
    label = row.run_id
    if row.snapshot_json:
        try:
            label = RunSnapshot.model_validate_json(row.snapshot_json).evaluation_name
        except Exception:
            label = row.run_id
    # Keep the legacy target envelope until the frontend contract is updated.
    return TaskTarget(type="evaluation_campaign", id=row.campaign_id or row.run_id, label=label)


def run_to_summary(row: EvaluationRunRow) -> TaskSummary:
    """One run row → a current-state task snapshot (GET /tasks)."""
    return TaskSummary(
        task_id=row.task_id or row.run_id,
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


def run_to_event(row: EvaluationRunRow, seq: int) -> EvaluationTaskEvent:
    """One run row → a canonical evaluation task event (SSE / latest)."""
    return EvaluationTaskEvent(
        task_id=row.task_id or row.run_id,
        state=map_state(row.operational_state),
        seq=seq,
        timestamp=datetime.now(timezone.utc),
        progress=_progress(row),
        step=None,
        error=None,
        target=_target(row),
        owner=row.created_by,
        detail=EvaluationDetail(
            campaign_id=row.campaign_id or row.run_id,
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
    "run_to_summary",
    "run_to_event",
]
