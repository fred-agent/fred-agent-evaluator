from __future__ import annotations

from fred_deepeval_cli.core.structural_checks import build_structural_checks


def test_sql_query_executed_returns_true_when_read_query_succeeds() -> None:
    trace = {
        "steps": [
            {"kind": "tool_call", "tool_name": "read_query", "arguments": {"query": "SELECT 1"}},
            {"kind": "tool_result", "tool_name": "read_query", "content": '{"rows": [{"value": 1}]}', "is_error": False},
        ]
    }
    checks = build_structural_checks(trace, profile="sql")
    check = next(c for c in checks if c.name == "sql_query_executed")
    assert check.passed is True


def test_sql_query_executed_returns_false_when_read_query_failed() -> None:
    trace = {
        "steps": [
            {"kind": "tool_call", "tool_name": "read_query", "arguments": {"query": "SELECT 1"}},
            {"kind": "tool_result", "tool_name": "read_query", "content": "Error: query failed", "is_error": True},
        ]
    }
    checks = build_structural_checks(trace, profile="sql")
    check = next(c for c in checks if c.name == "sql_query_executed")
    assert check.passed is False


def test_sql_no_execution_error_returns_true_for_clean_run() -> None:
    trace = {
        "error": None,
        "steps": [
            {"kind": "tool_result", "tool_name": "read_query", "content": '{"rows": [{"value": 1}]}', "is_error": False}
        ],
    }
    checks = build_structural_checks(trace, profile="sql")
    check = next(c for c in checks if c.name == "sql_no_execution_error")
    assert check.passed is True


def test_sql_no_execution_error_returns_false_for_global_error() -> None:
    trace = {"error": "backend failure", "steps": []}
    checks = build_structural_checks(trace, profile="sql")
    check = next(c for c in checks if c.name == "sql_no_execution_error")
    assert check.passed is False


def test_sql_query_executed_returns_true_when_list_tabular_datasets_succeeds() -> None:
    trace = {
        "steps": [
            {"kind": "tool_call", "tool_name": "list_tabular_datasets", "arguments": {}},
            {"kind": "tool_result", "tool_name": "list_tabular_datasets", "content": '["commandes"]', "is_error": False},
        ]
    }
    checks = build_structural_checks(trace, profile="sql")
    check = next(c for c in checks if c.name == "sql_query_executed")
    assert check.passed is True


def test_sql_query_executed_is_skipped_when_no_tools_called() -> None:
    trace = {"steps": []}
    checks = build_structural_checks(trace, profile="sql")
    check = next(c for c in checks if c.name == "sql_query_executed")
    assert check.passed is None


def test_build_structural_checks_returns_sql_checks_for_sql_profile() -> None:
    trace = {
        "steps": [
            {"kind": "tool_call", "tool_name": "read_query"},
            {"kind": "tool_result", "tool_name": "read_query", "content": "results", "is_error": False},
        ],
        "error": None,
    }
    checks = build_structural_checks(trace, profile="sql")
    names = [c.name for c in checks]
    assert "sql_query_executed" in names
    assert "sql_no_execution_error" in names
