from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from fred_core import M2MTokenProvider
from fred_core.kpi import BaseKPIWriter, Dims, NoOpKPIWriter
from opentelemetry.trace import Status, StatusCode

from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.model.judge_calls import (
    ACTOR,
    CallFailure,
    JudgeCallStats,
    classify,
    track_case_calls,
)
from fred_evaluation_backend.runs.store import RunStore
from fred_evaluation_backend.telemetry.otel import get_tracer

if TYPE_CHECKING:
    # Type-only: the API image never installs fred-deepeval-cli (`scoring`
    # extra is worker-only), so this must never become a runtime import here — this
    # module is imported by the API process to register the Temporal workflow.
    from fred_deepeval_cli.core.models import EvaluationMetricResult

logger = logging.getLogger(__name__)


async def execute_and_score_case(
    *,
    case_id: str,
    created_by: str,
    input: str,
    expected_output: str | None,
    agent_id: str | None,
    agent_instance_id: str | None = None,
    session_id: str,
    evaluate_url: str,
    team_id: str,
    token_provider: M2MTokenProvider | None = None,
    profile: str,
    judge,
    custom_metrics: list | None = None,
    metrics: list[str] | None = None,
    store: RunStore,
    agent_client: AgentClient,
    run_id: str,
    agent_profile_overrides: dict[str, str] | None = None,
    kpi: BaseKPIWriter | None = None,
) -> None:
    tracer = get_tracer()
    with tracer.start_as_current_span("eval.case") as span:
        span.set_attribute("eval.run_id", run_id)
        span.set_attribute("eval.case_id", case_id)
        span.set_attribute("eval.profile", profile)
        span.set_attribute("gen_ai.prompt", input[:500])
        # Langfuse v3 OTLP semantic attributes for session grouping
        span.set_attribute("session.id", run_id)
        span.set_attribute("user.id", created_by)
        await _execute_and_score_case_inner(
            span=span,
            case_id=case_id,
            run_id=run_id,
            created_by=created_by,
            input=input,
            expected_output=expected_output,
            agent_id=agent_id,
            agent_instance_id=agent_instance_id,
            session_id=session_id,
            evaluate_url=evaluate_url,
            team_id=team_id,
            token_provider=token_provider,
            profile=profile,
            judge=judge,
            custom_metrics=custom_metrics,
            metrics=metrics,
            store=store,
            agent_client=agent_client,
            agent_profile_overrides=agent_profile_overrides,
            kpi=kpi or NoOpKPIWriter(),
        )


async def _execute_and_score_case_inner(
    *,
    span,
    case_id: str,
    created_by: str,
    run_id: str,
    input: str,
    expected_output: str | None,
    agent_id: str | None,
    agent_instance_id: str | None = None,
    session_id: str,
    evaluate_url: str,
    team_id: str,
    token_provider: M2MTokenProvider | None = None,
    profile: str,
    judge,
    custom_metrics: list | None = None,
    metrics: list[str] | None = None,
    store: RunStore,
    agent_client: AgentClient,
    agent_profile_overrides: dict[str, str] | None = None,
    kpi: BaseKPIWriter,
) -> None:
    from fred_deepeval_cli.core.evaluator import classify_outcome
    from fred_deepeval_cli.core.profiles import resolve_profile
    from fred_deepeval_cli.core.scorer import score_trace
    from fred_deepeval_cli.core.structural_checks import build_structural_checks

    stats = track_case_calls(run_id, case_id)
    await store.update_case_result(
        case_id,
        status="running",
        outcome="unknown",
        verdict="inconclusive",
        actual_output=None,
        latency_ms=None,
        execution_error=None,
        scoring_errors_json=None,
        structural_checks_json=None,
        actual_model_name=None,
    )

    logger.debug("[ACTIVITY] calling agent case=%s", case_id)
    agent_started = time.perf_counter()
    try:
        eval_trace = await agent_client.evaluate(
            evaluate_url=evaluate_url,
            team_id=team_id,
            agent_id=agent_id,
            agent_instance_id=agent_instance_id,
            session_id=session_id,
            input=input,
            token_provider=token_provider,
            agent_profile_overrides=agent_profile_overrides,
        )
    except Exception as exc:
        agent_ms = _elapsed_ms(agent_started)
        failure = classify(exc)
        _record_agent_call(kpi, agent_ms, failure)
        logger.error(
            "event=agent_call_failed run=%s case=%s error_code=%s http_status=%s "
            "exception_type=%s agent_ms=%.0f message=%s",
            run_id,
            case_id,
            failure.code,
            failure.http_status,
            failure.exception_type,
            agent_ms,
            failure.message,
        )
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(failure)))
        span.set_attribute("eval.verdict", "failed")
        await store.update_case_result(
            case_id,
            status="error",
            outcome="execution_error",
            verdict="failed",
            actual_output=None,
            latency_ms=None,
            execution_error=str(failure),
            scoring_errors_json=None,
            structural_checks_json=None,
            actual_model_name=None,
        )
        await emit_run_event(run_id, case_id, "case_error", store)
        record_case_end(
            kpi, run_id=run_id, case_id=case_id, verdict="error", agent_ms=agent_ms
        )
        return
    agent_ms = _elapsed_ms(agent_started)
    _record_agent_call(kpi, agent_ms, None)

    trace_dict = eval_trace.model_dump()
    logger.info(
        "[TRACE] case=%s tools_called=%s steps_count=%d",
        case_id,
        eval_trace.tools_called,
        len(eval_trace.steps),
    )

    try:
        outcome = classify_outcome(trace_dict)
        resolved_profile = resolve_profile(trace_dict, explicit_profile=profile)
        structural_checks = build_structural_checks(
            trace_dict, profile=resolved_profile
        )

        metric_results: list[EvaluationMetricResult] = []
        scoring_errors: list[str] = []
        if judge is not None:
            # DeepEval scores synchronously: a thread keeps the worker's loop free.
            metric_results, scoring_errors = await asyncio.to_thread(
                score_trace,
                trace_dict,
                profile=resolved_profile,
                expected_output=expected_output,
                judge=judge,
                custom_metrics=custom_metrics,
                metrics=metrics,
            )
    except Exception as exc:
        failure = classify(exc)
        logger.exception(
            "event=case_scoring_failed run=%s case=%s error_code=%s exception_type=%s "
            "message=%s",
            run_id,
            case_id,
            failure.code,
            failure.exception_type,
            failure.message,
        )
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(failure)))
        span.set_attribute("eval.verdict", "failed")
        await store.update_case_result(
            case_id,
            status="error",
            outcome="execution_error",
            verdict="failed",
            actual_output=eval_trace.output,
            latency_ms=eval_trace.latency_ms,
            execution_error=str(failure),
            scoring_errors_json=None,
            structural_checks_json=None,
            actual_model_name=eval_trace.model_name,
        )
        await emit_run_event(run_id, case_id, "case_error", store)
        record_case_end(
            kpi,
            run_id=run_id,
            case_id=case_id,
            verdict="error",
            agent_ms=agent_ms,
            stats=stats,
        )
        return

    for m in metric_results:
        if m.verdict == "error":
            logger.error(
                "event=metric_error run=%s case=%s metric=%s error_code=%s error=%s",
                run_id,
                case_id,
                m.name,
                m.error_code or "unknown",
                m.error,
            )

    structural_ok = all(c.passed is not False for c in structural_checks)
    metrics_ok = (
        all(m.verdict == "passed" for m in metric_results) if metric_results else True
    )
    metrics_insufficient_only = (
        (
            not metrics_ok
            and all(
                m.verdict in ("passed", "insufficient", "skipped")
                for m in metric_results
            )
        )
        if metric_results
        else False
    )
    if structural_ok and not scoring_errors:
        if metrics_ok:
            verdict = "passed"
        elif metrics_insufficient_only:
            verdict = "insufficient"
        else:
            verdict = "failed"
    else:
        verdict = "failed"

    # Set OTel span attributes with final results
    span.set_attribute("eval.verdict", verdict)
    span.set_attribute("eval.outcome", outcome)
    if eval_trace.latency_ms is not None:
        span.set_attribute("eval.latency_ms", eval_trace.latency_ms)
    for m in metric_results:
        if m.score is not None:
            span.set_attribute(f"eval.metric.{m.name}.score", m.score)
        span.set_attribute(f"eval.metric.{m.name}.verdict", m.verdict)

    metric_summary = ", ".join(
        f"{m.name}={round(m.score * 100)}%"
        for m in metric_results
        if m.score is not None
    )
    span.set_attribute(
        "gen_ai.completion",
        f"verdict={verdict} | {metric_summary}"
        if metric_summary
        else f"verdict={verdict}",
    )

    if verdict == "failed":
        span.set_status(Status(StatusCode.ERROR, "case failed"))
    else:
        span.set_status(Status(StatusCode.OK))

    await store.update_case_result(
        case_id,
        status="completed",
        outcome=outcome,
        verdict=verdict,
        actual_output=eval_trace.output,
        latency_ms=eval_trace.latency_ms,
        execution_error=eval_trace.error,
        scoring_errors_json=json.dumps(scoring_errors) if scoring_errors else None,
        structural_checks_json=json.dumps([c.model_dump() for c in structural_checks]),
        actual_model_name=eval_trace.model_name,
    )

    # This activity is retryable, so scoring a case must be repeatable: drop any
    # rows a previous attempt left behind before writing this attempt's.
    await store.delete_metrics_by_case(case_id)
    for metric in metric_results:
        await store.create_metric_result(
            case_id=case_id,
            run_id=run_id,
            name=metric.name,
            provider=metric.provider,
            score=metric.score,
            threshold=metric.threshold,
            verdict=metric.verdict,
            explanation=metric.explanation,
            error=metric.error,
        )

    await emit_run_event(run_id, case_id, "case_completed", store)
    record_case_end(
        kpi,
        run_id=run_id,
        case_id=case_id,
        verdict=verdict,
        agent_ms=agent_ms,
        stats=stats,
        metric_errors=sum(1 for m in metric_results if m.verdict == "error"),
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _record_agent_call(
    kpi: BaseKPIWriter, agent_ms: float, failure: CallFailure | None
) -> None:
    dims: Dims = {
        "status": "error" if failure else "ok",
        "error_code": failure.code if failure else "none",
        "http_status": str(failure.http_status)
        if failure and failure.http_status
        else "none",
    }
    try:
        kpi.emit(
            name="eval.agent_call_latency_ms",
            type="timer",
            value=agent_ms,
            unit="ms",
            dims=dims,
            actor=ACTOR,
        )
    except Exception:
        logger.warning(
            "KPI emission failed for eval.agent_call_latency_ms", exc_info=True
        )


def record_case_end(
    kpi: BaseKPIWriter,
    *,
    run_id: str,
    case_id: str,
    verdict: str,
    agent_ms: float | None = None,
    stats: JudgeCallStats | None = None,
    metric_errors: int = 0,
) -> None:
    """Count the case outcome and log the one summary line every finished case gets.

    `verdict` is the case verdict, or `error` when the case could not run.
    """
    stats = stats or JudgeCallStats()
    try:
        kpi.count("eval.cases_total", dims={"status": verdict}, actor=ACTOR)
    except Exception:
        logger.warning("KPI emission failed for eval.cases_total", exc_info=True)
    logger.info(
        "event=eval_case_done run=%s case=%s verdict=%s agent_ms=%s judge_calls=%d "
        "judge_retries=%d judge_failures=%d judge_ms=%.0f throttle_ms=%.0f "
        "metric_errors=%d",
        run_id,
        case_id,
        verdict,
        f"{agent_ms:.0f}" if agent_ms is not None else "none",
        stats.calls,
        stats.retries,
        stats.failures,
        stats.call_ms,
        stats.throttle_ms,
        metric_errors,
    )


async def emit_run_event(
    run_id: str,
    case_id: str,
    kind: str,
    store: RunStore,
) -> None:
    """Record a per-case run event (SSE / `evaluation_event` table).

    Why this exists: it's the one place that knows the `{"case_id": ...}`
    payload shape for case-scoped events, so every caller — success, agent
    error, scoring error, or a per-case setup failure caught in the Temporal
    activity wrapper (`workers/workflow.py::run_case_for_run`) — stays
    consistent. Public (no leading underscore) because it's shared across
    `workers/activities.py` and `workers/workflow.py`.
    """
    payload = json.dumps({"case_id": case_id})
    await store.create_run_event(run_id, kind=kind, payload_json=payload)
