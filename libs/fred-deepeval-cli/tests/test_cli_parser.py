from __future__ import annotations

import pytest

from fred_deepeval_cli.cli.main import build_parser


def test_build_parser_parses_score_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("FRED_SEARCH_POLICY", raising=False)

    parser = build_parser()
    args = parser.parse_args(
        [
            "score",
            "--base-url",
            "http://127.0.0.1:8000/fred/agents/v2",
            "--agent-id",
            "fred.test.assistant",
            "--input",
            "echo bonjour",
            "--session-id",
            "eval-001",
            "--user-id",
            "alice",
        ]
    )

    assert args.command == "score"
    assert args.profile == "auto"
    assert args.base_url == "http://127.0.0.1:8000/fred/agents/v2"
    assert args.agent_id == "fred.test.assistant"
    assert args.input == "echo bonjour"
    assert args.session_id == "eval-001"
    assert args.user_id == "alice"
    assert args.team_id is None
    assert args.access_token is None
    assert args.search_policy is None
