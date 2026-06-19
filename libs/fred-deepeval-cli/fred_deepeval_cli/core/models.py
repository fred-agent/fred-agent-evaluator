from __future__ import annotations

from typing import Literal
from pydantic import BaseModel


class EvaluationMetricResult(BaseModel):
    name: str
    provider: str
    score: float | None
    threshold: float | None = None
    verdict: Literal["passed", "insufficient", "skipped", "error"]
    explanation: str | None = None
    error: str | None = None


class StructuralCheckResult(BaseModel):
    name: str
    passed: bool | None  # None = skipped (not applicable)
    detail: str | None = None


class EvaluationCaseRequest(BaseModel):
    agent_id: str
    input: str
    session_id: str
    expected_output: str | None = None
    profile: str = "auto"
    runtime_context: dict = {}


class EvaluationCaseResult(BaseModel):
    schema_version: Literal["1"] = "1"
    outcome: Literal["success", "execution_error", "degraded", "hitl_blocked", "unknown"]
    profile: str
    structural_checks: list[StructuralCheckResult]
    metrics: list[EvaluationMetricResult]
    latency_ms: int | None = None
    actual_output: str | None = None
    execution_error: str | None = None
    scoring_errors: list[str] = []