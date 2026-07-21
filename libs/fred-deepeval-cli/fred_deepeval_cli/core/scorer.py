from __future__ import annotations

import logging

import litellm
from deepeval.test_case import LLMTestCase

from fred_deepeval_cli.core.models import CustomMetricSpec, EvaluationMetricResult

# Quiet LiteLLM's per-request chatter, which is voluminous enough to bury a run's
# own logs. WARNING, not CRITICAL: rate limits and retries are exactly the signal an
# operator needs when an evaluation starts failing, and silencing them hides the
# cause of the failure rather than the noise.
#
# The root logger is deliberately left alone. `logging.getLogger("root")` is not a
# private namespace — Python resolves that name to the real root logger — so setting
# it here silenced the entire host application from the moment this module was
# imported, which for the evaluation worker is the first time it scores a case.
# Choosing log levels is the application's job, never a library's.
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

# GEval asks the judge for token logprobs to compute a fine-grained score. Providers like
# Mistral reject `logprobs`/`top_logprobs` outright, which would fail every custom metric.
# Telling litellm to drop unsupported params lets GEval fall back to a direct score on
# those providers; the built-in metrics never send these params, so they are unaffected.
litellm.drop_params = True


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
    custom_metrics: list[CustomMetricSpec] | None = None,
) -> tuple[list[EvaluationMetricResult], list[str]]:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        BaseMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
        GEval,
    )

    test_case = _trace_to_test_case(trace, expected_output=expected_output)
    retrieval_context = trace.get("retrieval_context") or []

    def _metric(cls, **kwargs):
        return cls(model=judge, async_mode=False, **kwargs)

    # Annotated as the base type: the list is heterogeneous (built-ins + GEval), and
    # inferring it from the first element would reject every later append.
    metrics: list[BaseMetric] = [_metric(AnswerRelevancyMetric)]

    if profile == "rag" and retrieval_context:
        metrics.append(_metric(FaithfulnessMetric))
        metrics.append(_metric(ContextualRelevancyMetric))
        if expected_output:
            metrics.append(_metric(ContextualPrecisionMetric))
            metrics.append(_metric(ContextualRecallMetric))

    # User-defined criteria: each becomes a GEval judged in plain language. The result
    # slots into the same measure/verdict loop below, indistinguishable from a built-in.
    for spec in custom_metrics or []:
        metrics.append(
            _metric(
                GEval,
                name=spec.name,
                criteria=spec.criteria,
                evaluation_params=spec.to_llm_params(),
                threshold=spec.threshold,
            )
        )

    results: list[EvaluationMetricResult] = []
    scoring_errors: list[str] = []

    for metric in metrics:
        # Built-in metrics report their class name (AnswerRelevancyMetric, …). A GEval is
        # generic — every custom criterion is the same class — so it must report the
        # user-given name instead, or all custom metrics would collapse to "GEval".
        # Matched on the class name rather than isinstance(): the offline tests swap the
        # DeepEval metric classes for fakes, so GEval is not always a real type here.
        # `__qualname__`, not `__name__`: DeepEval shadows `__name__` with a property
        # returning a display label ("Answer Relevancy"), hiding the class name.
        class_name = type(metric).__qualname__
        name = (
            getattr(metric, "name", class_name) if class_name == "GEval" else class_name
        )
        try:
            metric.measure(test_case)
            results.append(
                EvaluationMetricResult(
                    name=name,
                    provider="deepeval",
                    score=metric.score,
                    verdict="passed" if metric.success else "insufficient",
                    explanation=getattr(metric, "reason", None),
                )
            )
        except Exception as e:
            scoring_errors.append(f"{name}: {e}")
            results.append(
                EvaluationMetricResult(
                    name=name,
                    provider="deepeval",
                    score=None,
                    verdict="error",
                    error=str(e),
                )
            )

    return results, scoring_errors
