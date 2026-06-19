from __future__ import annotations

import httpx

from fred_deepeval_cli.core.models import (
    EvaluationCaseRequest,
    EvaluationCaseResult,
)
from fred_deepeval_cli.core.profiles import resolve_profile
from fred_deepeval_cli.core.structural_checks import build_structural_checks
from fred_deepeval_cli.core.scorer import score_trace


def classify_outcome(trace: dict) -> str:
    if trace.get("error"):
        return "execution_error"
    if any(step.get("kind") == "awaiting_human" for step in trace.get("steps", [])):
        return "hitl_blocked"
    if any(step.get("kind") == "node_error" for step in trace.get("steps", [])):
        return "degraded"
    if trace.get("output"):
        return "success"
    return "unknown"


def fetch_trace(
    base_url: str,
    request: EvaluationCaseRequest,
    access_token: str | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    payload = {
        "agent_id": request.agent_id,
        "input": request.input,
        "session_id": request.session_id,
        "runtime_context": request.runtime_context,
    }

    with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0, read=None)) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/agents/evaluate",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("Evaluate response must be a JSON object.")
        return result


def evaluate_case_sync(
    base_url: str,
    request: EvaluationCaseRequest,
    judge=None,
    access_token: str | None = None,
) -> EvaluationCaseResult:
    try:
        trace = fetch_trace(base_url, request, access_token=access_token)
    except Exception as e:
        return EvaluationCaseResult(
            outcome="execution_error",
            profile=request.profile,
            structural_checks=[],
            metrics=[],
            execution_error=str(e),
        )

    outcome = classify_outcome(trace)
    profile = resolve_profile(trace, explicit_profile=request.profile)
    structural_checks = build_structural_checks(trace, profile=profile)

    metrics, scoring_errors = [], []
    if judge is not None:
        metrics, scoring_errors = score_trace(
            trace,
            profile=profile,
            expected_output=request.expected_output,
            judge=judge,
        )

    return EvaluationCaseResult(
        outcome=outcome,
        profile=profile,
        structural_checks=structural_checks,
        metrics=metrics,
        actual_output=trace.get("output"),
        latency_ms=trace.get("latency_ms"),
        execution_error=trace.get("error"),
        scoring_errors=scoring_errors,
    )