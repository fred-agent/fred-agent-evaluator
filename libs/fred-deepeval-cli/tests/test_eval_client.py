from __future__ import annotations

from fred_deepeval_cli.core.models import EvaluationCaseRequest


def test_evaluation_case_request_builds_runtime_context() -> None:
    request = EvaluationCaseRequest(
        agent_id="fred.github.rag_expert",
        input="Quels sont les trois métriques ?",
        session_id="eval-001",
        runtime_context={
            "user_id": "alice",
            "team_id": "team-alpha",
            "search_policy": "semantic",
        },
    )
    assert request.runtime_context["user_id"] == "alice"
    assert request.runtime_context["team_id"] == "team-alpha"
    assert request.runtime_context["search_policy"] == "semantic"


def test_evaluation_case_request_defaults() -> None:
    request = EvaluationCaseRequest(
        agent_id="fred.test.assistant",
        input="echo bonjour",
        session_id="eval-001",
    )
    assert request.profile == "auto"
    assert request.expected_output is None
    assert request.runtime_context == {}
