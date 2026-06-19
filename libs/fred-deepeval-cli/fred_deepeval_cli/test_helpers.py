from __future__ import annotations

import httpx


def make_response(payload: dict) -> httpx.Response:
    request = httpx.Request(
        "POST",
        "http://127.0.0.1:8000/fred/agents/v2/agents/evaluate",
    )
    return httpx.Response(200, json=payload, request=request)


def make_trace(
    *,
    session_id: str = "eval-001",
    agent_id: str = "fred.test.assistant",
    agent_tags: list[str] | None = None,
    input: str = "echo bonjour",
    output: str | None = "Echo: echo bonjour",
    error: str | None = None,
    latency_ms: int = 123,
    model_name: str | None = None,
    token_usage: dict | None = None,
    finish_reason: str | None = None,
    steps: list[dict] | None = None,
    retrieval_context: list[str] | None = None,
    tools_called: list[str] | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_tags": agent_tags or [],
        "input": input,
        "output": output,
        "error": error,
        "latency_ms": latency_ms,
        "model_name": model_name,
        "token_usage": token_usage,
        "finish_reason": finish_reason,
        "steps": steps or [],
        "retrieval_context": retrieval_context or [],
        "tools_called": tools_called or [],
    }
