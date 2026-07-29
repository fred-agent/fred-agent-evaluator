from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fred_evaluation_backend.runs.metrics_catalog import BUILTIN_METRIC_IDS


class ManagedInstanceTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["managed_instance"]
    agent_instance_id: str


class RuntimeAgentTarget(BaseModel):
    """Historical target kind — no longer accepted on creation (EVAL-04)."""

    kind: Literal["runtime_agent"]
    runtime_id: str
    agent_id: str


EvaluationTarget = ManagedInstanceTarget | RuntimeAgentTarget


class RunSnapshot(BaseModel):
    schema_version: Literal["1"] = "1"
    evaluation_name: str
    evaluation_version: str
    target: EvaluationTarget
    resolved_target_config: dict[str, str] | None = None
    profile: str
    judge_profile_id: str
    execution: dict[str, int] | None = None


class CustomMetricSpecInput(BaseModel):
    """API-side twin of `fred_deepeval_cli.core.models.CustomMetricSpec`.

    Validates shape only — not whether `parameters` names are valid
    `LLMTestCaseParams` members, since that check imports `deepeval`, which
    the API image never installs (see `dockerfiles/Dockerfile-api`). An
    unknown parameter name is instead caught by the worker's own
    `CustomMetricSpec.model_validate()` and surfaces as a per-case scoring
    error rather than a run-creation error.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    criteria: str = Field(min_length=1)
    parameters: list[str] = Field(min_length=1)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class StartRunRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    team_id: str
    target: ManagedInstanceTarget
    metrics: list[str] = Field(min_length=1)
    custom_metrics: list[CustomMetricSpecInput] = Field(default_factory=list)

    @field_validator("metrics")
    @classmethod
    def _known_metrics(cls, value: list[str]) -> list[str]:
        unknown = set(value) - BUILTIN_METRIC_IDS
        if unknown:
            allowed = sorted(BUILTIN_METRIC_IDS)
            raise ValueError(f"unknown metrics {sorted(unknown)}; allowed: {allowed}")
        return value


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
    # The authenticated identity that launched the run — surfaced in the frontend's
    # "Run information" panel as its author.
    created_by: str
    target: EvaluationTarget
    profile: str
    judge_profile_id: str
    # The metric selection this run was started with — read back so a caller (e.g. the
    # frontend's one-click rerun) can reuse the same choice instead of guessing a default.
    metrics: list[str]
    custom_metrics: list[CustomMetricSpecInput]
    operational_state: str
    verdict: Literal["pending", "passed", "failed", "inconclusive"]
    total_cases: int
    completed_cases: int
    passed_cases: int
    failed_cases: int
    insufficient_cases: int
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


class StoredRunAnalysis(BaseModel):
    """On-disk shape of `evaluation_run.analysis_json` — the analyze endpoint
    stores the result wrapped, so readers parse it declaratively rather than
    indexing into a raw dict."""

    analysis: RunAnalysisResult


class RunAnalysisResponse(BaseModel):
    run_id: str
    analysis: RunAnalysisResult
    cached: bool


class RunReportEvaluation(BaseModel):
    """The definition this run executed, denormalised into the report.

    Copied rather than referenced: a report is an archive, so it must stay
    readable after the evaluation it came from is deleted.
    """

    evaluation_id: str
    name: str
    version: str
    team_id: str
    # Resolved from the Control Plane at report time. The id alone is opaque: a report
    # is meant to be archived or read by an LLM judge, neither of which can do anything
    # with a bare UUID. None when the lookup fails — the report is still worth having.
    team_name: str | None = None
    author: str | None  # declared in the document; None when not provided
    created_by: str  # authenticated uploader — verified
    origin: str
    completeness: str
    created_at: datetime


class RunReportResponse(BaseModel):
    """Self-contained JSON record of one run — for archiving, or for an LLM judge.

    Everything needed to interpret the result without a second call: what was
    asked (`evaluation`), how it was executed (`run.snapshot` — target, profile,
    judge), what came out per case (`cases`, each with its metric scores and the
    judge's explanations), and the aggregate view (`run` counters,
    `metric_averages`, optional cached `analysis`).
    """

    schema_version: Literal["1"] = "1"
    generated_at: datetime
    evaluation: RunReportEvaluation
    run: EvaluationRun
    metric_averages: dict[str, float] | None = None
    analysis: RunAnalysisResult | None = None
    cases: list[EvaluationCaseResponse]
