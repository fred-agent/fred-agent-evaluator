from __future__ import annotations

import logging
from datetime import datetime, timezone

from fred_core.sql import make_session_factory, use_session
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fred_evaluation_backend.runs.models import (
    EvaluationCaseRow,
    EvaluationEventRow,
    EvaluationExportDeliveryRow,
    EvaluationMetricResultRow,
    EvaluationRunRow,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class RunStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = make_session_factory(engine)

    async def create_case(
        self,
        *,
        case_id: str,
        run_id: str,
        external_id: str | None,
        input: str,
        expected_output: str | None,
        session: AsyncSession | None = None,
    ) -> EvaluationCaseRow:
        row = EvaluationCaseRow(
            case_id=case_id,
            campaign_id=None,
            run_id=run_id,
            external_id=external_id,
            input=input,
            expected_output=expected_output,
            status="pending",
            verdict="pending",
        )
        async with use_session(self._sessions, session) as s:
            s.add(row)
        return row

    async def list_cases_by_run(
        self,
        run_id: str,
        offset: int = 0,
        limit: int = 50,
        session: AsyncSession | None = None,
    ) -> list[EvaluationCaseRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationCaseRow)
                        .where(EvaluationCaseRow.run_id == run_id)
                        .offset(offset)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def get_case(
        self,
        case_id: str,
        session: AsyncSession | None = None,
    ) -> EvaluationCaseRow | None:
        async with use_session(self._sessions, session) as s:
            return await s.get(EvaluationCaseRow, case_id)

    async def create_metric_result(
        self,
        *,
        case_id: str,
        name: str,
        provider: str,
        score: float | None,
        threshold: float | None,
        verdict: str,
        explanation: str | None,
        error: str | None,
        run_id: str,
        session: AsyncSession | None = None,
    ) -> EvaluationMetricResultRow:
        row = EvaluationMetricResultRow(
            case_id=case_id,
            campaign_id=None,
            run_id=run_id,
            name=name,
            provider=provider,
            score=str(score) if score is not None else None,
            threshold=str(threshold) if threshold is not None else None,
            verdict=verdict,
            explanation=explanation,
            error=error,
        )
        async with use_session(self._sessions, session) as s:
            s.add(row)
        return row

    async def update_case_result(
        self,
        case_id: str,
        *,
        status: str,
        outcome: str,
        verdict: str,
        actual_output: str | None,
        latency_ms: int | None,
        execution_error: str | None,
        scoring_errors_json: str | None,
        structural_checks_json: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        async with use_session(self._sessions, session) as s:
            row = await s.get(EvaluationCaseRow, case_id)
            if row:
                row.status = status
                row.outcome = outcome
                row.verdict = verdict
                row.actual_output = actual_output
                row.latency_ms = latency_ms
                row.execution_error = execution_error
                row.scoring_errors_json = scoring_errors_json
                row.structural_checks_json = structural_checks_json

    async def create_run_event(
        self,
        run_id: str,
        *,
        kind: str,
        payload_json: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        from sqlalchemy import func

        async with use_session(self._sessions, session) as s:
            next_seq_result = await s.execute(
                select(func.coalesce(func.max(EvaluationEventRow.seq), -1) + 1).where(
                    EvaluationEventRow.run_id == run_id
                )
            )
            next_seq = next_seq_result.scalar() or 0
            s.add(
                EvaluationEventRow(
                    campaign_id=None,
                    run_id=run_id,
                    seq=next_seq,
                    kind=kind,
                    payload_json=payload_json,
                )
            )

    async def list_metrics_by_case(
        self,
        case_id: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationMetricResultRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationMetricResultRow).where(
                            EvaluationMetricResultRow.case_id == case_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def create_run(
        self,
        *,
        run_id: str,
        evaluation_id: str,
        team_id: str,
        created_by: str,
        task_id: str,
        target_kind: str,
        target_runtime_id: str | None,
        target_agent_id: str | None,
        target_instance_id: str | None,
        profile: str,
        judge_profile_id: str,
        total_cases: int,
        custom_metrics_json: str | None,
        snapshot_json: str,
        session: AsyncSession | None = None,
    ) -> EvaluationRunRow:
        row = EvaluationRunRow(
            run_id=run_id,
            campaign_id=None,
            evaluation_id=evaluation_id,
            team_id=team_id,
            created_by=created_by,
            task_id=task_id,
            target_kind=target_kind,
            target_runtime_id=target_runtime_id,
            target_agent_id=target_agent_id,
            target_instance_id=target_instance_id,
            profile=profile,
            judge_profile_id=judge_profile_id,
            custom_metrics_json=custom_metrics_json,
            snapshot_json=snapshot_json,
            operational_state="pending",
            verdict="pending",
            total_cases=total_cases,
            created_at=_utcnow(),
        )
        async with use_session(self._sessions, session) as s:
            s.add(row)
        return row

    async def get_run(
        self,
        run_id: str,
        session: AsyncSession | None = None,
    ) -> EvaluationRunRow | None:
        async with use_session(self._sessions, session) as s:
            return await s.get(EvaluationRunRow, run_id)

    async def list_runs_by_evaluation(
        self,
        evaluation_id: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationRunRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRunRow)
                        .where(EvaluationRunRow.evaluation_id == evaluation_id)
                        .order_by(EvaluationRunRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def list_runs_by_state(
        self,
        operational_state: str,
        limit: int = 10,
        session: AsyncSession | None = None,
    ) -> list[EvaluationRunRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRunRow)
                        .where(EvaluationRunRow.operational_state == operational_state)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def list_runs_by_team(
        self,
        team_id: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationRunRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRunRow)
                        .where(EvaluationRunRow.team_id == team_id)
                        .order_by(EvaluationRunRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def list_runs_by_creator(
        self,
        created_by: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationRunRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRunRow)
                        .where(EvaluationRunRow.created_by == created_by)
                        .order_by(EvaluationRunRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def get_run_by_task_id(
        self,
        task_id: str,
        session: AsyncSession | None = None,
    ) -> EvaluationRunRow | None:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRunRow)
                        .where(EvaluationRunRow.task_id == task_id)
                        .limit(1)
                    )
                )
                .scalars()
                .all()
            )
        return rows[0] if rows else None

    async def list_metrics_by_run(
        self,
        run_id: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationMetricResultRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationMetricResultRow).where(
                            EvaluationMetricResultRow.run_id == run_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def update_run_aggregates(
        self,
        run_id: str,
        *,
        completed_cases: int,
        passed_cases: int,
        failed_cases: int,
        execution_error_cases: int,
        scoring_error_cases: int,
        verdict: str,
        operational_state: str,
        metric_averages_json: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        async with use_session(self._sessions, session) as s:
            row = await s.get(EvaluationRunRow, run_id)
            if row:
                row.completed_cases = completed_cases
                row.passed_cases = passed_cases
                row.failed_cases = failed_cases
                row.execution_error_cases = execution_error_cases
                row.scoring_error_cases = scoring_error_cases
                row.verdict = verdict
                row.operational_state = operational_state
                row.metric_averages_json = metric_averages_json

    async def update_run_analysis(
        self,
        run_id: str,
        analysis_json: str,
        session: AsyncSession | None = None,
    ) -> None:
        async with use_session(self._sessions, session) as s:
            row = await s.get(EvaluationRunRow, run_id)
            if row is None:
                raise ValueError(f"Run {run_id} not found")
            row.analysis_json = analysis_json
            await s.flush()

    async def list_run_events(
        self,
        run_id: str,
        after_seq: int = -1,
        session: AsyncSession | None = None,
    ) -> list[EvaluationEventRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationEventRow)
                        .where(EvaluationEventRow.run_id == run_id)
                        .where(EvaluationEventRow.seq > after_seq)
                        .order_by(EvaluationEventRow.seq)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def update_run_state(
        self,
        run_id: str,
        operational_state: str,
        session: AsyncSession | None = None,
    ) -> None:
        async with use_session(self._sessions, session) as s:
            row = await s.get(EvaluationRunRow, run_id)
            if row:
                row.operational_state = operational_state

    async def delete_run(
        self,
        run_id: str,
        session: AsyncSession | None = None,
    ) -> bool:
        async with use_session(self._sessions, session) as s:
            row = await s.get(EvaluationRunRow, run_id)
            if row is None:
                return False
            for table in (
                EvaluationMetricResultRow,
                EvaluationEventRow,
                EvaluationExportDeliveryRow,
                EvaluationCaseRow,
            ):
                await s.execute(delete(table).where(table.run_id == run_id))
            await s.delete(row)
            return True


EvaluationStore = RunStore
