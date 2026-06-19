from __future__ import annotations

SUPPORTED_PROFILES = {"rag", "sql", "workflow", "default"}


def resolve_profile(trace: dict, explicit_profile: str = "auto") -> str:
    if explicit_profile != "auto" and explicit_profile in SUPPORTED_PROFILES:
        return explicit_profile

    agent_tags = set(trace.get("agent_tags", []))

    if "rag" in agent_tags:
        return "rag"

    if "sql" in agent_tags:
        return "sql"

    if "workflow" in agent_tags:
        return "workflow"

    return "default"