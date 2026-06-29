"""Capture service: turn an agent's real conversations into a QuestionSet.

Flow (EVAL-DATASET Phase 2):
1. read the agent's history from the runtime (filtered team + agent + period),
   propagating the caller's JWT;
2. pair user→assistant messages per `exchange_id` into QuestionCandidates;
3. build and persist a QuestionSet in status `captured` (no triage yet — Phase 3).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fred_evaluation_backend.datasets.schemas import (
    QuestionCandidate,
    QuestionSet,
    QuestionSetStatus,
)
from fred_evaluation_backend.datasets.store import DatasetStore
from fred_evaluation_backend.execution.history_client import (
    CapturedMessage,
    HistoryClient,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def messages_to_candidates(messages: list[CapturedMessage]) -> list[QuestionCandidate]:
    """Pair user→assistant messages of the same turn (exchange_id) into candidates.

    One candidate per turn: the user message is the question, the first assistant
    message of the same exchange is the answer. Messages without a user part are
    skipped (a turn with no question is not an evaluation candidate). Messages are
    assumed ordered (timestamp, session, rank), as returned by the runtime.
    """
    # Group by (session_id, exchange_id); fall back to a per-message key when the
    # exchange_id is missing so unrelated turns are not merged.
    groups: dict[tuple[str, str], list[CapturedMessage]] = {}
    order: list[tuple[str, str]] = []
    for m in messages:
        key = (m.session_id, m.exchange_id or f"_norank_{len(order)}")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)

    candidates: list[QuestionCandidate] = []
    for key in order:
        group = groups[key]
        user_msg = next((m for m in group if m.role == "user"), None)
        if user_msg is None:
            continue  # no question → not a candidate
        assistant_msg = next((m for m in group if m.role == "assistant"), None)
        candidates.append(
            QuestionCandidate(
                candidate_id=str(uuid.uuid4()),
                question=user_msg.content,
                answer=assistant_msg.content if assistant_msg else None,
                source_session_id=user_msg.session_id,
                source_exchange_id=user_msg.exchange_id,
                captured_at=user_msg.timestamp,
            )
        )
    return candidates


class CaptureService:
    def __init__(self, *, store: DatasetStore, history_client: HistoryClient) -> None:
        self._store = store
        self._history = history_client

    async def import_from_history(
        self,
        *,
        team_id: str,
        agent_instance_id: str,
        period_from: datetime,
        period_to: datetime,
        created_by: str,
        bearer_token: str | None,
        keep_threshold: int = 4,
        extra_filters: dict[str, str] | None = None,
        max_messages: int | None = None,
    ) -> QuestionSet:
        messages = await self._history.fetch_all(
            agent_instance_id=agent_instance_id,
            team_id=team_id,
            period_from=period_from,
            period_to=period_to,
            bearer_token=bearer_token,
            max_messages=max_messages,
        )
        candidates = messages_to_candidates(messages)
        now = _utcnow()
        qs = QuestionSet(
            question_set_id=str(uuid.uuid4()),
            team_id=team_id,
            agent_id=agent_instance_id,
            created_by=created_by,
            status=QuestionSetStatus.captured,
            period_from=period_from,
            period_to=period_to,
            extra_filters=extra_filters or {},
            keep_threshold=keep_threshold,
            candidates=candidates,
            created_at=now,
            updated_at=now,
        )
        await self._store.create_question_set(qs)
        logger.info(
            "[CAPTURE] question_set=%s team=%s agent=%s candidates=%d",
            qs.question_set_id,
            team_id,
            agent_instance_id,
            len(candidates),
        )
        return qs
