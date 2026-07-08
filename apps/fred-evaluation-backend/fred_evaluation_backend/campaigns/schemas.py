from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Cible ────────────────────────────────────────────────────────────────────


class ManagedInstanceTarget(BaseModel):
    kind: Literal["managed_instance"]
    agent_instance_id: str


class RuntimeAgentTarget(BaseModel):
    kind: Literal["runtime_agent"]
    runtime_id: str
    agent_id: str


EvaluationTarget = ManagedInstanceTarget | RuntimeAgentTarget


# ── Création de campagne ──────────────────────────────────────────────────────


class EvaluationCaseInput(BaseModel):
    external_id: str | None = None
    input: str
    expected_output: str | None = None
    tags: list[str] = []


class EvaluationDataset(BaseModel):
    name: str
    version: str | None = None
    cases: list[EvaluationCaseInput] = Field(min_length=1)


class EvaluationExecutionOptions(BaseModel):
    max_concurrency: int = Field(default=3, ge=1, le=10)
    case_timeout_seconds: int = Field(default=600, ge=30, le=900)
    # EVAL-02: run the campaign later instead of immediately. Carried to the bus task
    # (`task_run.scheduled_for`) and to Temporal as a `start_delay`, so the schedule is
    # durable — it survives redeploys of the API and the worker.
    #
    # A past (or absent) value means "run now". Timezone-aware only: a naive datetime is
    # ambiguous across the API pod's and the worker's clocks, so it is rejected rather
    # than silently interpreted as UTC.
    #
    # No maximum horizon is enforced here — that bound must equal the platform retention
    # window (RFC EVAL-02 §5.2, still open), and inventing a value would only hide the
    # question.
    scheduled_for: datetime | None = None

    @field_validator("scheduled_for")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(
                "scheduled_for must be timezone-aware (e.g. 2026-07-15T09:00:00Z)"
            )
        return value


class CreateEvaluationCampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    team_id: str
    target: EvaluationTarget
    dataset: EvaluationDataset
    profile: str = "auto"
    judge_profile_id: str
    execution: EvaluationExecutionOptions = EvaluationExecutionOptions()


# ── Réponses ──────────────────────────────────────────────────────────────────


class CampaignCreatedResponse(BaseModel):
    campaign_id: str
    run_id: str
    task_id: str | None
    state: str


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
    campaign_id: str
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


class EvaluationCampaignResponse(BaseModel):
    schema_version: Literal["1"] = "1"
    campaign_id: str
    run_id: str | None
    task_id: str | None
    name: str
    team_id: str
    created_by: str
    target: EvaluationTarget
    dataset_name: str
    dataset_version: str | None
    profile: str
    judge_profile_id: str
    operational_state: str
    verdict: str
    total_cases: int
    completed_cases: int
    passed_cases: int
    failed_cases: int
    execution_error_cases: int
    scoring_error_cases: int
    metric_averages: dict[str, float] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EvaluationCampaignListResponse(BaseModel):
    campaigns: list[EvaluationCampaignResponse]
    total: int


class EvaluationCaseListResponse(BaseModel):
    cases: list[EvaluationCaseResponse]
    total: int


class CampaignAnalysisResult(BaseModel):
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    risk_level: str


class CampaignAnalysisResponse(BaseModel):
    campaign_id: str
    analysis: CampaignAnalysisResult
    cached: bool
