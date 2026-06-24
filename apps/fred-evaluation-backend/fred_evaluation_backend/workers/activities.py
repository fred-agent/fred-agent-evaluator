from __future__ import annotations

import json
import logging

from fred_core import M2MTokenProvider
from fred_sdk.contracts.execution import ExecutionGrant
from opentelemetry.trace import Status, StatusCode

from fred_evaluation_backend.campaigns.store import EvaluationStore
from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.telemetry.otel import get_tracer

logger = logging.getLogger(__name__)


async def execute_and_score_case(
    *,
    case_id: str,
    campaign_id: str,
    created_by: str,
    input: str,
    expected_output: str | None,
    agent_id: str | None,
    agent_instance_id: str | None = None,
    session_id: str,
    evaluate_url: str,
    execution_grant: ExecutionGrant,
    token_provider: M2MTokenProvider | None = None,
    profile: str,
    judge,
    store: EvaluationStore,
    agent_client: AgentClient,
) -> None:
    tracer = get_tracer()
    with tracer.start_as_current_span("eval.case") as span:
        span.set_attribute("eval.campaign_id", campaign_id)
        span.set_attribute("eval.case_id", case_id)
        span.set_attribute("eval.profile", profile)
        span.set_attribute("gen_ai.prompt", input[:500])
        # Langfuse v3 OTLP semantic attributes for session grouping
        span.set_attribute("session.id", campaign_id)
        span.set_attribute("user.id", created_by)
        await _execute_and_score_case_inner(
            span=span,
            case_id=case_id,
            campaign_id=campaign_id,
            created_by=created_by,
            input=input,
            expected_output=expected_output,
            agent_id=agent_id,
            agent_instance_id=agent_instance_id,
            session_id=session_id,
            evaluate_url=evaluate_url,
            execution_grant=execution_grant,
            token_provider=token_provider,
            profile=profile,
            judge=judge,
            store=store,
            agent_client=agent_client,
        )


async def _execute_and_score_case_inner(
    *,
    span,
    case_id: str,
    campaign_id: str,
    created_by: str,
    input: str,
    expected_output: str | None,
    agent_id: str | None,
    agent_instance_id: str | None = None,
    session_id: str,
    evaluate_url: str,
    execution_grant: ExecutionGrant,
    token_provider: M2MTokenProvider | None = None,
    profile: str,
    judge,
    store: EvaluationStore,
    agent_client: AgentClient,
) -> None:
    from fred_deepeval_cli.core.evaluator import classify_outcome
    from fred_deepeval_cli.core.profiles import resolve_profile
    from fred_deepeval_cli.core.scorer import score_trace
    from fred_deepeval_cli.core.structural_checks import build_structural_checks

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
    )

    print(f"[ACTIVITY-DEBUG] case={case_id} calling agent_client.evaluate", flush=True)
    try:
        eval_trace = await agent_client.evaluate(
            evaluate_url=evaluate_url,
            execution_grant=execution_grant,
            agent_id=agent_id,
            agent_instance_id=agent_instance_id,
            session_id=session_id,
            input=input,
            token_provider=token_provider,
        )
    except Exception as exc:
        logger.error("[ACTIVITY] agent call failed case=%s: %s", case_id, exc)
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        span.set_attribute("eval.verdict", "failed")
        await store.update_case_result(
            case_id,
            status="error",
            outcome="execution_error",
            verdict="failed",
            actual_output=None,
            latency_ms=None,
            execution_error=str(exc),
            scoring_errors_json=None,
            structural_checks_json=None,
        )
        await _emit_event(campaign_id, case_id, "case_error", store)
        return

    trace_dict = eval_trace.model_dump()
    print(
        f"[ACTIVITY-DEBUG] case={case_id} tools_called={eval_trace.tools_called} steps_count={len(eval_trace.steps)}",
        flush=True,
    )
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

        metrics: list = []
        scoring_errors: list[str] = []
        if judge is not None:
            metrics, scoring_errors = score_trace(
                trace_dict,
                profile=resolved_profile,
                expected_output=expected_output,
                judge=judge,
            )
    except Exception as exc:
        logger.error("[ACTIVITY] scoring failed case=%s: %s", case_id, exc)
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        span.set_attribute("eval.verdict", "failed")
        await store.update_case_result(
            case_id,
            status="error",
            outcome="execution_error",
            verdict="failed",
            actual_output=eval_trace.output,
            latency_ms=eval_trace.latency_ms,
            execution_error=str(exc),
            scoring_errors_json=None,
            structural_checks_json=None,
        )
        await _emit_event(campaign_id, case_id, "case_error", store)
        return

    structural_ok = all(c.passed is not False for c in structural_checks)
    metrics_ok = all(m.verdict == "passed" for m in metrics) if metrics else True
    metrics_insufficient_only = (
        (
            not metrics_ok
            and all(m.verdict in ("passed", "insufficient", "skipped") for m in metrics)
        )
        if metrics
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
    for m in metrics:
        if m.score is not None:
            span.set_attribute(f"eval.metric.{m.name}.score", m.score)
        span.set_attribute(f"eval.metric.{m.name}.verdict", m.verdict)

    metric_summary = ", ".join(
        f"{m.name}={round(m.score * 100)}%" for m in metrics if m.score is not None
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
    )

    for metric in metrics:
        await store.create_metric_result(
            case_id=case_id,
            campaign_id=campaign_id,
            name=metric.name,
            provider=metric.provider,
            score=metric.score,
            threshold=metric.threshold,
            verdict=metric.verdict,
            explanation=metric.explanation,
            error=metric.error,
        )

    await _emit_event(campaign_id, case_id, "case_completed", store)


async def _emit_event(
    campaign_id: str,
    case_id: str,
    kind: str,
    store: EvaluationStore,
) -> None:
    await store.create_event(
        campaign_id,
        kind=kind,
        payload_json=json.dumps({"case_id": case_id}),
    )
