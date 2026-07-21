"""Pydantic domain models for the evaluation catalog domain."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QuestionSetStatus(str, Enum):
    captured = "captured"
    scoring = "scoring"
    curated = "curated"


class EvaluationCompleteness(str, Enum):
    minimal = "minimal"
    complete = "complete"


EvaluationOrigin = Literal["capture", "upload", "manual"]


class QuestionTriageScore(BaseModel):
    is_relevant_question: int = Field(ge=1, le=5)
    is_rag_question: int = Field(ge=1, le=5)
    answerability: int = Field(ge=1, le=5)
    raw_llm: str | None = None


class QuestionCandidate(BaseModel):
    candidate_id: str
    question: str
    answer: str | None = None
    source_session_id: str | None = None
    source_exchange_id: str | None = None
    captured_at: datetime
    triage: QuestionTriageScore | None = None
    kept: bool = False


class QuestionSet(BaseModel):
    schema_version: Literal["2"] = "2"
    question_set_id: str
    team_id: str
    agent_id: str
    created_by: str
    status: QuestionSetStatus = QuestionSetStatus.captured
    period_from: datetime | None = None
    period_to: datetime | None = None
    extra_filters: dict[str, str] = Field(default_factory=dict)
    keep_threshold: int = Field(default=4, ge=1, le=5)
    candidates: list[QuestionCandidate] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvaluationCase(BaseModel):
    external_id: str | None = None
    input: str
    expected_output: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_candidate_id: str | None = None
    source_session_id: str | None = None


class Evaluation(BaseModel):
    schema_version: Literal["2"] = "2"
    evaluation_id: str
    name: str
    version: str
    team_id: str
    created_by: str
    origin: EvaluationOrigin
    source_question_set_id: str | None = None
    completeness: EvaluationCompleteness = EvaluationCompleteness.minimal
    cases: list[EvaluationCase] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _derive_completeness(self) -> Evaluation:
        self.completeness = (
            EvaluationCompleteness.complete
            if self.cases and all(c.expected_output for c in self.cases)
            else EvaluationCompleteness.minimal
        )
        return self


_MAX_DATASET_CASES = 200


class CreateEvaluationRequest(BaseModel):
    """The evaluation document, as authored and uploaded.

    Self-describing: it carries its own identity (`name`, optional `version`) and
    provenance (`author`), so an archived file can be read without the request
    that created it. `version` is the identity when declared — (team, name,
    version) is unique — and is assigned by the server (`v1`, `v2`, …) when left
    out. `author` is declarative and may be any label; the authenticated
    uploader is recorded separately as `created_by` and cannot be forged.
    """

    team_id: str
    name: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    author: str | None = Field(default=None, max_length=255)
    origin: Literal["upload", "manual"]
    source_filename: str | None = None
    cases: list[EvaluationCase] = Field(min_length=1, max_length=_MAX_DATASET_CASES)


class EvaluationSummaryResponse(BaseModel):
    evaluation_id: str
    name: str
    version: str
    author: str | None  # declared in the document; None when not provided
    created_by: str  # authenticated uploader — verified, never client-supplied
    team_id: str
    origin: EvaluationOrigin
    completeness: EvaluationCompleteness
    case_count: int
    created_at: datetime


class EvaluationDetailResponse(EvaluationSummaryResponse):
    cases: list[EvaluationCase]


class EvaluationListResponse(BaseModel):
    evaluations: list[EvaluationSummaryResponse]
    total: int
