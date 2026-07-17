from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# ── Cible ────────────────────────────────────────────────────────────────────


class ManagedInstanceTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["managed_instance"]
    agent_instance_id: str


class RuntimeAgentTarget(BaseModel):
    """Historical target kind — no longer accepted on creation (EVAL-04).

    Kept only so historical run snapshots can still render the old
    `runtime_agent` target shape.
    """

    kind: Literal["runtime_agent"]
    runtime_id: str
    agent_id: str


# Response-only union — see RuntimeAgentTarget's docstring. Request bodies use
# `ManagedInstanceTarget` directly, no union, no discriminator needed.
EvaluationTarget = ManagedInstanceTarget | RuntimeAgentTarget


# ── EVAL-05 — Run and its frozen snapshot (RFC §9.5) ─────────────────────────
#
# A Run is one execution of an Evaluation against a chosen target/policy. Multiple
# Runs of the same Evaluation are compared, so each Run freezes a RunSnapshot at Start
# time: the immutability of the Evaluation pins the case content, but says nothing about
# which target/prompt/config was used or which server-side execution defaults applied.


class RunSnapshot(BaseModel):
    schema_version: Literal["1"] = "1"
    evaluation_name: str
    evaluation_version: str
    target: EvaluationTarget
    # prompt/config id, corpus tag set — whatever prepare-execution resolves at Start.
    resolved_target_config: dict[str, str] | None = None
    profile: str
    judge_profile_id: str
    # Concurrency/timeout actually used, kept as a plain dict until execution options
    # are re-introduced as a typed model (they are server-owned defaults this release).
    execution: dict[str, int] | None = None


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str
    target: ManagedInstanceTarget


class RunCreatedResponse(BaseModel):
    run_id: str
    evaluation_id: str
    task_id: str | None
    state: str


class EvaluationRun(BaseModel):
    schema_version: Literal["1"] = "1"
    run_id: str
    evaluation_id: str
    task_id: str | None
    target: EvaluationTarget
    profile: str
    judge_profile_id: str
    operational_state: str
    verdict: Literal["pending", "passed", "failed", "inconclusive"]
    total_cases: int
    completed_cases: int
    passed_cases: int
    failed_cases: int
    execution_error_cases: int
    scoring_error_cases: int
    snapshot: RunSnapshot
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EvaluationMetricResultResponse(BaseModel):
    name: str
    provider: str
    score: float | None
    threshold: float | None
    verdict: Literal["passed", "insufficient", "failed", "skipped", "error"]
    explanation: str | None
    error: str | None


class StructuralCheckResponse(BaseModel):
    name: str
    passed: bool | None


class EvaluationCaseResponse(BaseModel):
    case_id: str
    # EVAL-05: run-created cases have no campaign. run_id is the identity now.
    campaign_id: str | None = None
    run_id: str | None
    external_id: str | None
    status: str
    outcome: str | None
    verdict: str
    input: str
    expected_output: str | None
    actual_output: str | None
    profile: str | None
    latency_ms: int | None
    execution_error: str | None
    scoring_errors: list[str]
    metrics: list[EvaluationMetricResultResponse]
    structural_checks: list[StructuralCheckResponse]
    started_at: datetime | None
    completed_at: datetime | None


class EvaluationCaseListResponse(BaseModel):
    cases: list[EvaluationCaseResponse]
    total: int


class RunAnalysisResult(BaseModel):
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    risk_level: str


class RunAnalysisResponse(BaseModel):
    run_id: str
    analysis: RunAnalysisResult
    cached: bool
