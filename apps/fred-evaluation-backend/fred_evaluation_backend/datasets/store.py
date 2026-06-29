"""Persistence for the dataset domain (Phase 2: QuestionSet only).

Follows the existing evaluator pattern (`campaigns/store.py`): typed columns for
what we filter on, a JSON column for the nested list. The Pydantic models in
`schemas.py` are the schema and the (de)serialization guarantee — we dump them to
the JSON columns on write and validate them back on read.
"""

from __future__ import annotations

import json
import logging

from fred_core.sql import make_session_factory, use_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fred_evaluation_backend.datasets.models import QuestionSetRow
from fred_evaluation_backend.datasets.schemas import (
    QuestionCandidate,
    QuestionSet,
    QuestionSetStatus,
)

logger = logging.getLogger(__name__)


def _row_to_model(row: QuestionSetRow) -> QuestionSet:
    candidates = [
        QuestionCandidate.model_validate(c)
        for c in json.loads(row.candidates_json or "[]")
    ]
    return QuestionSet(
        question_set_id=row.question_set_id,
        team_id=row.team_id,
        agent_id=row.agent_id,
        created_by=row.created_by,
        status=QuestionSetStatus(row.status),
        period_from=row.period_from,
        period_to=row.period_to,
        extra_filters=json.loads(row.extra_filters_json or "{}"),
        keep_threshold=row.keep_threshold,
        candidates=candidates,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class DatasetStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = make_session_factory(engine)

    async def create_question_set(
        self, qs: QuestionSet, session: AsyncSession | None = None
    ) -> QuestionSet:
        row = QuestionSetRow(
            question_set_id=qs.question_set_id,
            team_id=qs.team_id,
            agent_id=qs.agent_id,
            created_by=qs.created_by,
            status=qs.status.value,
            period_from=qs.period_from,
            period_to=qs.period_to,
            keep_threshold=qs.keep_threshold,
            candidates_json=json.dumps(
                [c.model_dump(mode="json") for c in qs.candidates]
            ),
            extra_filters_json=json.dumps(qs.extra_filters),
            created_at=qs.created_at,
            updated_at=qs.updated_at,
        )
        async with use_session(self._sessions, session) as s:
            s.add(row)
        return qs

    async def get_question_set(
        self, question_set_id: str, session: AsyncSession | None = None
    ) -> QuestionSet | None:
        async with use_session(self._sessions, session) as s:
            row = await s.get(QuestionSetRow, question_set_id)
            return _row_to_model(row) if row is not None else None

    async def list_question_sets(
        self, team_id: str, limit: int = 200, session: AsyncSession | None = None
    ) -> list[QuestionSet]:
        async with use_session(self._sessions, session) as s:
            rows = (
                (
                    await s.execute(
                        select(QuestionSetRow)
                        .where(QuestionSetRow.team_id == team_id)
                        .order_by(QuestionSetRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_row_to_model(r) for r in rows]
