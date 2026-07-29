from __future__ import annotations

import logging
from datetime import datetime, timezone

from fred_core.sql import make_session_factory, use_session
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fred_evaluation_backend.evaluations.models import EvaluationRow

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# Columns an evaluation list may be sorted on. Whitelisted so a caller-supplied
# `sort` string can never reach the SQL layer as an arbitrary column reference.
_EVALUATION_SORT_COLUMNS = {
    "created_at": EvaluationRow.created_at,
    "name": EvaluationRow.name,
    "version": EvaluationRow.version,
}


def _evaluation_order_by(sort: str | None):
    """Ordering expression for a whitelisted `field:direction` sort, newest first by default."""
    field, _, direction = (sort or "created_at:desc").partition(":")
    column = _EVALUATION_SORT_COLUMNS.get(field, EvaluationRow.created_at)
    return column.asc() if direction == "asc" else column.desc()


def _team_evaluations_where(team_id: str, q: str | None) -> list[ColumnElement[bool]]:
    """Shared WHERE clauses for team-scoped evaluation reads: team match + optional
    case-insensitive name search, so list and count never diverge."""
    clauses: list[ColumnElement[bool]] = [EvaluationRow.team_id == team_id]
    if q:
        clauses.append(EvaluationRow.name.ilike(f"%{q}%"))
    return clauses


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
        author: str | None = None,
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
            author=author,
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

    async def version_exists(
        self,
        team_id: str,
        name: str,
        version: str,
        session: AsyncSession | None = None,
    ) -> bool:
        """A declared version is an identity: (team, name, version) must be unique."""
        async with use_session(self._sessions, session) as s:
            found = (
                (
                    await s.execute(
                        select(EvaluationRow.evaluation_id).where(
                            EvaluationRow.team_id == team_id,
                            EvaluationRow.name == name,
                            EvaluationRow.version == version,
                        )
                    )
                )
                .scalars()
                .first()
            )
        return found is not None

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
        *,
        offset: int = 0,
        limit: int | None = None,
        sort: str | None = None,
        q: str | None = None,
        session: AsyncSession | None = None,
    ) -> list[EvaluationRow]:
        # `limit=None` returns every evaluation for the team. The paginated read
        # endpoint passes an explicit limit; other callers keep the full list.
        async with use_session(self._sessions, session) as s:
            stmt = (
                select(EvaluationRow)
                .where(*_team_evaluations_where(team_id, q))
                .order_by(_evaluation_order_by(sort))
                .offset(offset)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = (await s.execute(stmt)).scalars().all()
        return list(rows)

    async def count_evaluations_by_team(
        self,
        team_id: str,
        *,
        q: str | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        async with use_session(self._sessions, session) as s:
            stmt = (
                select(func.count())
                .select_from(EvaluationRow)
                .where(*_team_evaluations_where(team_id, q))
            )
            return (await s.execute(stmt)).scalar_one()

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
