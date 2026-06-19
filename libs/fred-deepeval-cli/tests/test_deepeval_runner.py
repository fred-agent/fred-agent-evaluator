from __future__ import annotations

from unittest.mock import patch, MagicMock

from fred_deepeval_cli.core.scorer import score_trace
from fred_deepeval_cli.test_helpers import make_trace


class FakeMetric:
    def __init__(self, model=None, async_mode=False) -> None:
        self.score = 1.0
        self.success = True
        self.reason = None

    def measure(self, test_case) -> None:
        pass


def _patch_metrics():
    return patch.dict("sys.modules", {
        "deepeval.metrics": MagicMock(
            AnswerRelevancyMetric=FakeMetric,
            FaithfulnessMetric=FakeMetric,
            ContextualRelevancyMetric=FakeMetric,
            ContextualPrecisionMetric=FakeMetric,
            ContextualRecallMetric=FakeMetric,
        )
    })


def test_score_trace_without_retrieval_context_only_uses_answer_relevancy() -> None:
    with _patch_metrics():
        metrics, errors = score_trace(
            make_trace(retrieval_context=[], output="Echo: echo bonjour"),
            profile="default",
            judge=object(),
        )
    assert len(metrics) == 1
    assert errors == []


def test_score_trace_with_retrieval_context_adds_faithfulness() -> None:
    with _patch_metrics():
        metrics, errors = score_trace(
            make_trace(
                output="Réponse fondée sur le contexte.",
                retrieval_context=["chunk-1"],
                tools_called=["knowledge_search"],
            ),
            profile="rag",
            judge=object(),
        )
    assert len(metrics) > 1
    assert errors == []


def test_score_trace_with_sql_profile_only_uses_answer_relevancy() -> None:
    with _patch_metrics():
        metrics, errors = score_trace(
            make_trace(agent_tags=["sql"], output="Average: 548.7", retrieval_context=["schema"]),
            profile="sql",
            judge=object(),
        )
    assert len(metrics) == 1
    assert errors == []
