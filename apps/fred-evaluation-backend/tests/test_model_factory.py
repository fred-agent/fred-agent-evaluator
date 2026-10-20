"""Judge factory tests.

Focus: the ``vertex_ai`` provider is **keyless** — on GKE the judge reaches Vertex via
Application Default Credentials (Workload Identity), like knowledge-flow/fred-agents, so
it must NOT require a Mistral/OpenAI/LiteLLM API key. Every provider yields the
bounded model, carrying the profile's load limits.
"""

from __future__ import annotations

import pytest
from fred_core.common import ModelConfiguration

from fred_evaluation_backend.model.bounded_model import BoundedLiteLLMModel
from fred_evaluation_backend.model.factory import build_judge_model


def test_vertex_ai_is_keyless_and_prefixes_model(monkeypatch):
    # No provider key set: a keyed provider would raise; vertex_ai must not.
    for var in ("MISTRAL_API_KEY", "LITELLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    judge = build_judge_model(
        ModelConfiguration(provider="vertex_ai", name="gemini-2.5-flash")
    )

    assert isinstance(judge, BoundedLiteLLMModel)
    assert judge.name == "vertex_ai/gemini-2.5-flash"
    assert judge.api_key is None


def test_vertex_alias_preserves_existing_prefix():
    judge = build_judge_model(
        ModelConfiguration(provider="vertex", name="vertex_ai/gemini-2.5-pro")
    )
    assert judge.name == "vertex_ai/gemini-2.5-pro"


def test_litellm_provider_still_requires_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        build_judge_model(
            ModelConfiguration(
                provider="litellm",
                name="mistral/mistral-small-latest",
                settings={"api_key_env": "MISTRAL_API_KEY"},  # pragma: allowlist secret
            )
        )


def test_profile_limits_reach_the_model(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")  # pragma: allowlist secret
    judge = build_judge_model(
        ModelConfiguration(
            provider="litellm",
            name="mistral/mistral-small-latest",
            settings={
                "api_key_env": "MISTRAL_API_KEY",  # pragma: allowlist secret
                "max_attempts": 3,
                "request_timeout": 90,
            },
        ),
        role="analysis",
    )
    assert judge._call_policy.max_attempts == 3
    assert judge._call_policy.role == "analysis"
    assert judge.kwargs["request_timeout"] == 90
    assert judge.kwargs["num_retries"] == 0


def test_defaults_apply_when_a_profile_sets_no_limit():
    judge = build_judge_model(ModelConfiguration(provider="ollama", name="llama3"))
    assert judge._call_policy.max_attempts == 2
    assert judge.kwargs["request_timeout"] == 60
