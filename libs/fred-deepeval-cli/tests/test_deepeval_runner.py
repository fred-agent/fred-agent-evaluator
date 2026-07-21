from __future__ import annotations

from unittest.mock import MagicMock, patch

from fred_deepeval_cli.core.scorer import score_trace
from fred_deepeval_cli.test_helpers import make_trace


class FakeMetric:
    def __init__(self, model=None, async_mode=False) -> None:
        self.score = 1.0
        self.success = True
        self.reason = None

    def measure(self, test_case) -> None:
        pass


def _fake_metric_class(name: str) -> type:
    """A distinct subclass per metric id, so `type(metric).__qualname__` reports
    the same class name a real DeepEval metric would — `score_trace` names each
    result off that, and every fake sharing one `FakeMetric` class would collapse
    them all to the same name."""
    return type(name, (FakeMetric,), {})


def _patch_metrics():
    return patch.dict(
        "sys.modules",
        {
            "deepeval.metrics": MagicMock(
                AnswerRelevancyMetric=_fake_metric_class("AnswerRelevancyMetric"),
                FaithfulnessMetric=_fake_metric_class("FaithfulnessMetric"),
                ContextualRelevancyMetric=_fake_metric_class(
                    "ContextualRelevancyMetric"
                ),
                ContextualPrecisionMetric=_fake_metric_class(
                    "ContextualPrecisionMetric"
                ),
                ContextualRecallMetric=_fake_metric_class("ContextualRecallMetric"),
            )
        },
    )


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
            make_trace(
                agent_tags=["sql"],
                output="Average: 548.7",
                retrieval_context=["schema"],
            ),
            profile="sql",
            judge=object(),
        )
    assert len(metrics) == 1
    assert errors == []


# ── explicit metric selection (manual, replaces the automatic profile cascade) ──


def test_score_trace_explicit_metrics_selects_only_requested_metrics() -> None:
    with _patch_metrics():
        metrics, errors = score_trace(
            make_trace(output="hello", retrieval_context=[]),
            judge=object(),
            metrics=["faithfulness", "answer_relevancy"],
        )
    assert {m.name for m in metrics} == {"FaithfulnessMetric", "AnswerRelevancyMetric"}
    assert errors == []


def test_score_trace_explicit_metrics_ignores_profile_and_retrieval_context() -> None:
    """Selection is manual now — a `default`/non-rag profile must not suppress a
    metric the caller explicitly asked for, unlike the old automatic cascade."""
    with _patch_metrics():
        metrics, errors = score_trace(
            make_trace(output="hello", retrieval_context=[]),
            profile="default",
            judge=object(),
            metrics=["faithfulness"],
        )
    assert [m.name for m in metrics] == ["FaithfulnessMetric"]
    assert errors == []


def test_score_trace_explicit_metrics_skips_contextual_metrics_without_expected_output() -> (
    None
):
    with _patch_metrics():
        metrics, errors = score_trace(
            make_trace(output="hello", retrieval_context=["chunk"]),
            judge=object(),
            expected_output=None,
            metrics=["contextual_precision", "contextual_recall", "answer_relevancy"],
        )
    by_name = {m.name: m for m in metrics}
    assert by_name["ContextualPrecisionMetric"].verdict == "skipped"
    assert by_name["ContextualPrecisionMetric"].score is None
    assert by_name["ContextualRecallMetric"].verdict == "skipped"
    assert by_name["AnswerRelevancyMetric"].verdict != "skipped"
    assert errors == []


class GEval:
    """Named `GEval` on purpose: `score_trace` names a custom-metric result after
    `type(metric).__qualname__ == "GEval"`, not `isinstance()` — see the comment
    in `scorer.py`."""

    name: str | None
    score: float
    success: bool
    reason: str | None

    def __init__(
        self,
        model: object = None,
        async_mode: bool = False,
        name: str | None = None,
        **kwargs: object,
    ) -> None:
        self.name = name
        self.score = 1.0
        self.success = True
        self.reason = None

    def measure(self, _test_case: object) -> None:
        pass


def test_score_trace_explicit_empty_metrics_runs_nothing_but_custom_metrics() -> None:
    from fred_deepeval_cli.core.models import CustomMetricSpec

    with patch.dict(
        "sys.modules",
        {
            "deepeval.metrics": MagicMock(
                AnswerRelevancyMetric=FakeMetric,
                FaithfulnessMetric=FakeMetric,
                ContextualRelevancyMetric=FakeMetric,
                ContextualPrecisionMetric=FakeMetric,
                ContextualRecallMetric=FakeMetric,
                GEval=GEval,
            )
        },
    ):
        metrics, errors = score_trace(
            make_trace(output="hello"),
            judge=object(),
            metrics=[],
            custom_metrics=[
                CustomMetricSpec(
                    name="cites_source",
                    criteria="Must cite a source.",
                    parameters=["INPUT", "ACTUAL_OUTPUT"],
                )
            ],
        )
    assert [m.name for m in metrics] == ["cites_source"]
    assert errors == []
