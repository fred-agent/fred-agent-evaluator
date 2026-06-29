"""Pydantic domain models for the dataset domain.

Three concepts, two persisted models (see docs/rfc/EVAL-DATASET-RFC.md §6 P1):

- ``QuestionSet`` — capture + curation, mutable (``captured → scoring → curated``).
- ``EvaluationDataset`` — frozen, versioned; the input contract to campaigns.

``LLMTestCase`` is owned by DeepEval and never persisted — it is an ephemeral
projection built at scoring time, so it does not live here.

These models are both the schema and the guarantee (P3): nested/variable parts
(``candidates``, ``cases``) are stored in JSON columns and their shape is enforced
declaratively here, with no hand-written validation elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ── Enums ─────────────────────────────────────────────────────────────────────


class QuestionSetStatus(str, Enum):
    captured = "captured"  # imported, not yet triaged
    scoring = "scoring"  # triage running
    curated = "curated"  # triage done, ready to promote


class DatasetCompleteness(str, Enum):
    minimal = "minimal"  # input only → reference-free metrics
    complete = "complete"  # input + expected_output → all metrics


DatasetOrigin = Literal["capture", "upload", "manual"]


# ── Model A — QuestionSet (capture + curation) ────────────────────────────────


class QuestionTriageScore(BaseModel):
    """The 3 triage criteria, each scored 1..5, plus the raw judge output."""

    is_relevant_question: int = Field(ge=1, le=5)  # filters "thanks", "hi"…
    is_rag_question: int = Field(ge=1, le=5)  # is it actually a RAG query?
    answerability: int = Field(ge=1, le=5)  # answerable from the corpus?
    raw_llm: str | None = None


class QuestionCandidate(BaseModel):
    candidate_id: str
    question: str  # message role=user (from history)
    answer: str | None = None  # associated message role=assistant
    source_session_id: str | None = None
    source_exchange_id: str | None = None
    captured_at: datetime
    triage: QuestionTriageScore | None = None  # None until scored
    kept: bool = False  # True when all 3 criteria >= keep_threshold


class QuestionSet(BaseModel):
    schema_version: Literal["2"] = "2"
    question_set_id: str
    team_id: str
    agent_id: str
    created_by: str
    status: QuestionSetStatus = QuestionSetStatus.captured
    # import filters ("Analytics"-style)
    period_from: datetime | None = None
    period_to: datetime | None = None
    extra_filters: dict[str, str] = Field(default_factory=dict)  # user_id, session_id…
    keep_threshold: int = Field(default=4, ge=1, le=5)  # ">= 4/5" rule
    candidates: list[QuestionCandidate] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Model B — EvaluationDataset (frozen, versioned) ───────────────────────────


class DatasetCase(BaseModel):
    external_id: str | None = None
    input: str
    expected_output: str | None = None
    tags: list[str] = Field(default_factory=list)
    # provenance (curation traceability)
    source_candidate_id: str | None = None
    source_session_id: str | None = None


class EvaluationDataset(BaseModel):
    schema_version: Literal["2"] = "2"
    dataset_id: str
    name: str
    version: str  # immutable; a new curation produces a new version
    team_id: str
    created_by: str
    origin: DatasetOrigin
    source_question_set_id: str | None = None  # link to the originating QuestionSet
    # derived: minimal as soon as one case lacks expected_output (see validator)
    completeness: DatasetCompleteness = DatasetCompleteness.minimal
    cases: list[DatasetCase] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _derive_completeness(self) -> EvaluationDataset:
        """`completeness` is always derived from the cases, never trusted as input.

        complete only if every case has an expected_output; minimal otherwise
        (including the empty case list).
        """
        self.completeness = (
            DatasetCompleteness.complete
            if self.cases and all(c.expected_output for c in self.cases)
            else DatasetCompleteness.minimal
        )
        return self
