from __future__ import annotations

import logging

from deepeval.test_case import LLMTestCase

from fred_deepeval_cli.core.models import EvaluationMetricResult

logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.getLogger("root").setLevel(logging.CRITICAL)


def _normalize_retrieval_context(raw: list) -> list[str]:
    result = []
    for item in raw:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            result.append(item.get("content") or item.get("text") or str(item))
    return result


def _trace_to_test_case(trace: dict, expected_output: str | None = None) -> LLMTestCase:
    raw_context = trace.get("retrieval_context") or []
    retrieval_context = _normalize_retrieval_context(raw_context) if raw_context else []
    return LLMTestCase(
        input=trace.get("input", ""),
        actual_output=trace.get("output") or "",
        expected_output=expected_output,
        retrieval_context=retrieval_context,
    )


def score_trace(
    trace: dict,
    profile: str = "default",
    expected_output: str | None = None,
    judge=None,
) -> tuple[list[EvaluationMetricResult], list[str]]:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
    )

    test_case = _trace_to_test_case(trace, expected_output=expected_output)
    retrieval_context = trace.get("retrieval_context") or []

    def _metric(cls, **kwargs):
        return cls(model=judge, async_mode=False, **kwargs)

    metrics = [_metric(AnswerRelevancyMetric)]

    if profile == "rag" and retrieval_context:
        metrics.append(_metric(FaithfulnessMetric))
        metrics.append(_metric(ContextualRelevancyMetric))
        if expected_output:
            metrics.append(_metric(ContextualPrecisionMetric))
            metrics.append(_metric(ContextualRecallMetric))

    results: list[EvaluationMetricResult] = []
    scoring_errors: list[str] = []

    for metric in metrics:
        try:
            metric.measure(test_case)
            results.append(
                EvaluationMetricResult(
                    name=metric.__class__.__name__,
                    provider="deepeval",
                    score=metric.score,
                    verdict="passed" if metric.success else "insufficient",
                    explanation=getattr(metric, "reason", None),
                )
            )
        except Exception as e:
            scoring_errors.append(f"{metric.__class__.__name__}: {e}")
            results.append(
                EvaluationMetricResult(
                    name=metric.__class__.__name__,
                    provider="deepeval",
                    score=None,
                    verdict="error",
                    error=str(e),
                )
            )

    return results, scoring_errors
