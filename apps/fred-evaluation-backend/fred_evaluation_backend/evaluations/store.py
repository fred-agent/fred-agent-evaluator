from __future__ import annotations

import logging
from datetime import datetime, timezone

from fred_core.sql import make_session_factory, use_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fred_evaluation_backend.evaluations.models import EvaluationRow

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class EvaluationStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = make_session_factory(engine)

    async def create_evaluation(
        self,
        *,
        evaluation_id: str,
        name: str,
        version: str,
        team_id: str,
        created_by: str,
        origin: str,
        completeness: str,
        cases_json: str,
        session: AsyncSession | None = None,
    ) -> EvaluationRow:
        row = EvaluationRow(
            evaluation_id=evaluation_id,
            name=name,
            version=version,
            team_id=team_id,
            created_by=created_by,
            origin=origin,
            completeness=completeness,
            source_question_set_id=None,
            cases_json=cases_json,
            created_at=_utcnow(),
        )
        async with use_session(self._sessions, session) as s:
            s.add(row)
        return row

    async def get_evaluation(
        self,
        evaluation_id: str,
        session: AsyncSession | None = None,
    ) -> EvaluationRow | None:
        async with use_session(self._sessions, session) as s:
            return await s.get(EvaluationRow, evaluation_id)

    async def get_latest_version_number(
        self,
        team_id: str,
        name: str,
        session: AsyncSession | None = None,
    ) -> int:
        async with use_session(self._sessions, session) as s:
            versions = (
                (
                    await s.execute(
                        select(EvaluationRow.version).where(
                            EvaluationRow.team_id == team_id,
                            EvaluationRow.name == name,
                        )
                    )
                )
                .scalars()
                .all()
            )
        numbers = []
        for v in versions:
            try:
                numbers.append(int(str(v).lstrip("v")))
            except ValueError:
                continue
        return max(numbers, default=0)

    async def delete_evaluation(
        self,
        evaluation_id: str,
        session: AsyncSession | None = None,
    ) -> bool:
        async with use_session(self._sessions, session) as s:
            row = await s.get(EvaluationRow, evaluation_id)
            if row is None:
                return False
            await s.delete(row)
        return True

    async def list_evaluations_by_team(
        self,
        team_id: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRow)
                        .where(EvaluationRow.team_id == team_id)
                        .order_by(EvaluationRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def get_evaluations_by_ids(
        self,
        evaluation_ids: list[str],
        session: AsyncSession | None = None,
    ) -> dict[str, EvaluationRow]:
        if not evaluation_ids:
            return {}
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationRow).where(
                            EvaluationRow.evaluation_id.in_(set(evaluation_ids))
                        )
                    )
                )
                .scalars()
                .all()
            )
        return {row.evaluation_id: row for row in rows}
