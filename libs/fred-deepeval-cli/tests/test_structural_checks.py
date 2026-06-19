from __future__ import annotations

from fred_deepeval_cli.core.structural_checks import build_structural_checks


def test_rag_tool_used_returns_true_when_knowledge_search_was_called() -> None:
    trace = {"tools_called": ["knowledge_search"], "retrieval_context": []}
    checks = build_structural_checks(trace, profile="rag")
    rag_tool = next(c for c in checks if c.name == "rag_tool_used")
    assert rag_tool.passed is True


def test_rag_tool_used_returns_false_when_knowledge_search_was_not_called() -> None:
    trace = {"tools_called": [], "retrieval_context": []}
    checks = build_structural_checks(trace, profile="rag")
    rag_tool = next(c for c in checks if c.name == "rag_tool_used")
    assert rag_tool.passed is False


def test_rag_context_nonempty_returns_false_for_empty_context() -> None:
    trace = {"tools_called": [], "retrieval_context": []}
    checks = build_structural_checks(trace, profile="rag")
    ctx = next(c for c in checks if c.name == "rag_context_nonempty")
    assert ctx.passed is False


def test_rag_context_nonempty_returns_true_for_nonempty_context() -> None:
    trace = {"tools_called": ["knowledge_search"], "retrieval_context": ["chunk-1"]}
    checks = build_structural_checks(trace, profile="rag")
    ctx = next(c for c in checks if c.name == "rag_context_nonempty")
    assert ctx.passed is True


def test_build_structural_checks_returns_rag_checks_for_rag_profile() -> None:
    trace = {
        "tools_called": ["knowledge_search"],
        "retrieval_context": ["Document 1"],
    }
    checks = build_structural_checks(trace, profile="rag")
    names = [c.name for c in checks]
    assert "rag_tool_used" in names
    assert "rag_context_nonempty" in names
