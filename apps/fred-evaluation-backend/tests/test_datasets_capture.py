"""Phase 2 capture tests: exchange_id pairing + QuestionSet store round-trip.

Offline — pure mapping logic, plus a temporary SQLite file for the store.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from fred_evaluation_backend.campaigns.base import Base
from fred_evaluation_backend.datasets.schemas import QuestionSet, QuestionSetStatus
from fred_evaluation_backend.datasets.service import messages_to_candidates
from fred_evaluation_backend.datasets.store import DatasetStore
from fred_evaluation_backend.execution.history_client import CapturedMessage

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _msg(
    session: str, exchange: str, role: str, content: str, ts: datetime
) -> CapturedMessage:
    return CapturedMessage(
        session_id=session,
        user_id="alice",
        exchange_id=exchange,
        role=role,
        content=content,
        timestamp=ts,
    )


# ── mapping ───────────────────────────────────────────────────────────────────


def test_pairs_user_and_assistant_by_exchange_id():
    messages = [
        _msg("s1", "ex1", "user", "q1", _T0),
        _msg("s1", "ex1", "assistant", "a1", _T0),
        _msg("s1", "ex2", "user", "q2", _T0),
        _msg("s1", "ex2", "assistant", "a2", _T0),
    ]
    candidates = messages_to_candidates(messages)
    assert [(c.question, c.answer) for c in candidates] == [
        ("q1", "a1"),
        ("q2", "a2"),
    ]
    assert candidates[0].source_exchange_id == "ex1"


def test_answer_is_the_final_assistant_message_not_the_empty_tool_call():
    # A turn: user → assistant tool-call (no text) → assistant final answer.
    messages = [
        _msg("s1", "ex1", "user", "q1", _T0),
        _msg("s1", "ex1", "assistant", "", _T0),  # tool-call message, no text
        _msg("s1", "ex1", "assistant", "the real answer", _T0),
    ]
    candidates = messages_to_candidates(messages)
    assert len(candidates) == 1
    assert candidates[0].answer == "the real answer"


def test_user_without_answer_yields_candidate_with_none_answer():
    candidates = messages_to_candidates([_msg("s1", "ex1", "user", "q1", _T0)])
    assert len(candidates) == 1
    assert candidates[0].answer is None


def test_group_without_user_is_skipped():
    # An assistant-only exchange is not an evaluation candidate.
    candidates = messages_to_candidates([_msg("s1", "ex1", "assistant", "a1", _T0)])
    assert candidates == []


# ── store round-trip ──────────────────────────────────────────────────────────


async def _make_store(path: Path) -> tuple[DatasetStore, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return DatasetStore(engine), engine


def test_question_set_store_round_trip():
    async def run():
        with tempfile.TemporaryDirectory() as d:
            store, _ = await _make_store(Path(d) / "qs.db")
            qs = QuestionSet(
                question_set_id="qs-1",
                team_id="fredlab",
                agent_id="rico",
                created_by="alice",
                status=QuestionSetStatus.captured,
                candidates=messages_to_candidates(
                    [
                        _msg("s1", "ex1", "user", "q1", _T0),
                        _msg("s1", "ex1", "assistant", "a1", _T0),
                    ]
                ),
                created_at=_T0,
                updated_at=_T0,
            )
            _ = await store.create_question_set(qs)

            fetched = await store.get_question_set("qs-1")
            assert fetched is not None
            assert fetched.team_id == "fredlab"
            assert fetched.status is QuestionSetStatus.captured
            assert [c.question for c in fetched.candidates] == ["q1"]

            listed = await store.list_question_sets("fredlab")
            assert [q.question_set_id for q in listed] == ["qs-1"]

    asyncio.run(run())
