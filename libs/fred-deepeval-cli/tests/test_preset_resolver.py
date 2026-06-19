from __future__ import annotations

from fred_deepeval_cli.core.profiles import resolve_profile


def test_resolve_profile_returns_explicit_value_when_forced() -> None:
    trace = {"agent_tags": ["rag", "documents", "react"]}
    assert resolve_profile(trace, explicit_profile="sql") == "sql"


def test_resolve_profile_returns_rag_from_agent_tags() -> None:
    trace = {"agent_tags": ["rag", "documents", "react"]}
    assert resolve_profile(trace) == "rag"


def test_resolve_profile_returns_sql_from_agent_tags() -> None:
    trace = {"agent_tags": ["sql", "tabular", "react"]}
    assert resolve_profile(trace) == "sql"


def test_resolve_profile_returns_default_when_no_known_tag_is_present() -> None:
    trace = {"agent_tags": ["general", "react"]}
    assert resolve_profile(trace) == "default"
