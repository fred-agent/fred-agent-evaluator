from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock, patch

from fred_deepeval_cli.cli.main import run_score
from fred_deepeval_cli.core.models import EvaluationCaseResult, EvaluationMetricResult


def _make_result(outcome="success", profile="default", metrics=None) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        outcome=outcome,
        profile=profile,
        structural_checks=[],
        metrics=metrics or [
            EvaluationMetricResult(
                name="AnswerRelevancyMetric",
                provider="deepeval",
                score=1.0,
                verdict="passed",
            )
        ],
        actual_output="Echo: echo bonjour",
    )


@patch("fred_deepeval_cli.cli.main.build_judge")
@patch("fred_deepeval_cli.cli.main.evaluate_case_sync")
def test_run_score_success_returns_zero(
    mock_evaluate: MagicMock,
    mock_judge: MagicMock,
    capsys,
) -> None:
    mock_evaluate.return_value = _make_result()
    mock_judge.return_value = object()

    args = argparse.Namespace(
        base_url="http://127.0.0.1:8000/fred/agents/v2",
        agent_id="fred.test.assistant",
        input="echo bonjour",
        session_id="eval-005",
        user_id="alice",
        team_id=None,
        access_token=None,
        search_policy=None,
        profile="auto",
    )

    exit_code = run_score(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["outcome"] == "success"
    assert payload["profile"] == "default"


@patch("fred_deepeval_cli.cli.main.build_judge")
@patch("fred_deepeval_cli.cli.main.evaluate_case_sync")
def test_run_score_execution_error_returns_one(
    mock_evaluate: MagicMock,
    mock_judge: MagicMock,
    capsys,
) -> None:
    mock_evaluate.return_value = _make_result(outcome="execution_error")
    mock_judge.return_value = object()

    args = argparse.Namespace(
        base_url="http://127.0.0.1:8000/fred/agents/v2",
        agent_id="fred.test.assistant",
        input="echo bonjour",
        session_id="eval-006",
        user_id="alice",
        team_id=None,
        access_token=None,
        search_policy=None,
        profile="auto",
    )

    exit_code = run_score(args)
    assert exit_code == 1


# test_run_sql_scenarios.py → marquer comme skip car le script dépend du réseau
