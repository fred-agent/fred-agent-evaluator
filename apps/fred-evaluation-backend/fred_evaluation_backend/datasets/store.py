from __future__ import annotations

import logging
from datetime import datetime, timezone

from fred_core.sql import make_session_factory, use_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fred_evaluation_backend.datasets.models import EvaluationDatasetRow

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class DatasetStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = make_session_factory(engine)

    async def create_dataset(
        self,
        *,
        dataset_id: str,
        name: str,
        version: str,
        team_id: str,
        created_by: str,
        origin: str,
        completeness: str,
        cases_json: str,
        session: AsyncSession | None = None,
    ) -> EvaluationDatasetRow:
        row = EvaluationDatasetRow(
            dataset_id=dataset_id,
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

    async def get_dataset(
        self,
        dataset_id: str,
        session: AsyncSession | None = None,
    ) -> EvaluationDatasetRow | None:
        async with use_session(self._sessions, session) as s:
            return await s.get(EvaluationDatasetRow, dataset_id)

    async def list_datasets_by_team(
        self,
        team_id: str,
        session: AsyncSession | None = None,
    ) -> list[EvaluationDatasetRow]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationDatasetRow)
                        .where(EvaluationDatasetRow.team_id == team_id)
                        .order_by(EvaluationDatasetRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def get_datasets_by_ids(
        self,
        dataset_ids: list[str],
        session: AsyncSession | None = None,
    ) -> dict[str, EvaluationDatasetRow]:
        """Batch lookup for campaign-list rendering — avoids one query per campaign."""
        if not dataset_ids:
            return {}
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(EvaluationDatasetRow).where(
                            EvaluationDatasetRow.dataset_id.in_(set(dataset_ids))
                        )
                    )
                )
                .scalars()
                .all()
            )
        return {row.dataset_id: row for row in rows}
