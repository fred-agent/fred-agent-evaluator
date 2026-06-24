from __future__ import annotations

from fred_deepeval_cli.core.models import StructuralCheckResult


def _tool_steps(trace: dict, kind: str, tool_name: str) -> list[dict]:
    return [
        step
        for step in trace.get("steps", [])
        if step.get("kind") == kind and step.get("tool_name") == tool_name
    ]


def _has_tool_call(trace: dict, tool_name: str) -> bool:
    return bool(_tool_steps(trace, "tool_call", tool_name))


def _has_successful_tool_result(trace: dict, tool_name: str) -> bool:
    for step in _tool_steps(trace, "tool_result", tool_name):
        if step.get("is_error"):
            continue
        content = step.get("content") or ""
        if isinstance(content, str) and content.strip():
            if not content.lstrip().startswith("Error:"):
                return True
    return False


_SQL_DATA_TOOLS = {"read_query", "list_tabular_datasets", "get_tabular_dataset_schema"}


def build_structural_checks(
    trace: dict, profile: str = "default"
) -> list[StructuralCheckResult]:
    checks = []

    if profile == "rag":
        checks.append(
            StructuralCheckResult(
                name="rag_tool_used",
                passed="knowledge_search" in trace.get("tools_called", []),
            )
        )
        checks.append(
            StructuralCheckResult(
                name="rag_context_nonempty",
                passed=bool(trace.get("retrieval_context")),
            )
        )

    elif profile == "sql":
        any_tool_called = any(
            step.get("kind") == "tool_call" for step in trace.get("steps", [])
        )
        if not any_tool_called:
            sql_executed = None  # agent answered without tools — not applicable
        else:
            sql_executed = any(
                _has_tool_call(trace, tool) and _has_successful_tool_result(trace, tool)
                for tool in _SQL_DATA_TOOLS
            )
        checks.append(
            StructuralCheckResult(
                name="sql_query_executed",
                passed=sql_executed,
            )
        )
        checks.append(
            StructuralCheckResult(
                name="sql_no_execution_error",
                passed=not trace.get("error")
                and not any(
                    s.get("kind") == "node_error" or s.get("is_error")
                    for s in trace.get("steps", [])
                ),
            )
        )

    return checks
