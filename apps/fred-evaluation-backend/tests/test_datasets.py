"""Evaluation catalog domain model tests.

These lock in the Phase 1 contract from docs/rfc/EVAL-DATASET-RFC.md:
- the Pydantic models round-trip through JSON (the persistence boundary),
- `completeness` is derived from the cases (never trusted as input),
- a frozen dataset's version is part of its identity (versioning invariant).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fred_evaluation_backend.datasets.schemas import (
    Evaluation,
    EvaluationCase,
    EvaluationCompleteness,
    QuestionCandidate,
    QuestionSet,
    QuestionSetStatus,
    QuestionTriageScore,
)


def _now() -> datetime:
    return datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)


# ── completeness derivation ───────────────────────────────────────────────────


def _evaluation(cases: list[EvaluationCase], version: str = "v1") -> Evaluation:
    return Evaluation(
        evaluation_id="eval-1",
        name="MyDataset",
        version=version,
        team_id="team-1",
        created_by="alice",
        origin="upload",
        cases=cases,
        created_at=_now(),
    )


def test_completeness_complete_when_all_cases_have_expected_output():
    evaluation = _evaluation(
        [
            EvaluationCase(input="q1", expected_output="a1"),
            EvaluationCase(input="q2", expected_output="a2"),
        ]
    )
    assert evaluation.completeness is EvaluationCompleteness.complete


def test_completeness_minimal_when_one_case_lacks_expected_output():
    evaluation = _evaluation(
        [
            EvaluationCase(input="q1", expected_output="a1"),
            EvaluationCase(input="q2"),  # no expected_output
        ]
    )
    assert evaluation.completeness is EvaluationCompleteness.minimal


def test_completeness_minimal_for_empty_cases():
    assert _evaluation([]).completeness is EvaluationCompleteness.minimal


def test_completeness_is_derived_not_trusted_as_input():
    # Caller claims complete, but a case lacks expected_output → forced to minimal.
    evaluation = Evaluation(
        evaluation_id="eval-1",
        name="MyDataset",
        version="v1",
        team_id="team-1",
        created_by="alice",
        origin="upload",
        completeness=EvaluationCompleteness.complete,
        cases=[EvaluationCase(input="q1")],
        created_at=_now(),
    )
    assert evaluation.completeness is EvaluationCompleteness.minimal


# ── JSON round-trip (persistence boundary) ────────────────────────────────────


def test_evaluation_json_round_trip():
    evaluation = _evaluation(
        [EvaluationCase(input="q1", expected_output="a1", tags=["rag"])]
    )
    restored = Evaluation.model_validate_json(evaluation.model_dump_json())
    assert restored == evaluation


def test_question_set_json_round_trip():
    qs = QuestionSet(
        question_set_id="qs-1",
        team_id="team-1",
        agent_id="rico",
        created_by="alice",
        candidates=[
            QuestionCandidate(
                candidate_id="c1",
                question="Comment poser des congés ?",
                answer="Via FORYOU.",
                captured_at=_now(),
                triage=QuestionTriageScore(
                    is_relevant_question=5,
                    is_rag_question=4,
                    answerability=5,
                ),
                kept=True,
            )
        ],
        created_at=_now(),
        updated_at=_now(),
    )
    restored = QuestionSet.model_validate_json(qs.model_dump_json())
    assert restored == qs
    assert restored.status is QuestionSetStatus.captured


# ── versioning invariant ──────────────────────────────────────────────────────


def test_version_is_part_of_identity():
    cases = [EvaluationCase(input="q1")]
    v1 = _evaluation(cases, version="v1")
    v2 = _evaluation(cases, version="v2")
    # Same lineage (name), distinct frozen versions.
    assert v1.name == v2.name
    assert v1.version != v2.version
