"""Judge factory tests.

Focus: the ``vertex_ai`` provider is **keyless** — on GKE the judge reaches Vertex via
Application Default Credentials (Workload Identity), like knowledge-flow/fred-agents, so
it must NOT require a Mistral/OpenAI/LiteLLM API key. deepeval ships only in the
scoring/worker extra, so we stub ``LiteLLMModel`` to test the factory logic in isolation.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from fred_core.common import ModelConfiguration

from fred_evaluation_backend.model.factory import build_judge_model


def _stub_deepeval(monkeypatch) -> MagicMock:
    """Install a fake ``deepeval.models.llms`` so the lazy import inside the factory
    resolves without deepeval installed. Returns the ``LiteLLMModel`` mock."""
    litellm_model = MagicMock(name="LiteLLMModel")
    llms = types.ModuleType("deepeval.models.llms")
    llms.LiteLLMModel = litellm_model
    llms.GPTModel = MagicMock(name="GPTModel")
    models = types.ModuleType("deepeval.models")
    models.llms = llms
    root = types.ModuleType("deepeval")
    root.models = models
    monkeypatch.setitem(sys.modules, "deepeval", root)
    monkeypatch.setitem(sys.modules, "deepeval.models", models)
    monkeypatch.setitem(sys.modules, "deepeval.models.llms", llms)
    return litellm_model


def test_vertex_ai_is_keyless_and_prefixes_model(monkeypatch):
    litellm_model = _stub_deepeval(monkeypatch)
    # No provider key set: a keyed provider would raise; vertex_ai must not.
    for var in ("MISTRAL_API_KEY", "LITELLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    build_judge_model(ModelConfiguration(provider="vertex_ai", name="gemini-2.5-flash"))

    litellm_model.assert_called_once()
    kwargs = litellm_model.call_args.kwargs
    assert kwargs["model"] == "vertex_ai/gemini-2.5-flash"
    assert kwargs["api_key"] is None


def test_vertex_alias_preserves_existing_prefix(monkeypatch):
    litellm_model = _stub_deepeval(monkeypatch)
    build_judge_model(
        ModelConfiguration(provider="vertex", name="vertex_ai/gemini-2.5-pro")
    )
    assert litellm_model.call_args.kwargs["model"] == "vertex_ai/gemini-2.5-pro"


def test_litellm_provider_still_requires_key(monkeypatch):
    _stub_deepeval(monkeypatch)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        build_judge_model(
            ModelConfiguration(
                provider="litellm",
                name="mistral/mistral-small-latest",
                settings={"api_key_env": "MISTRAL_API_KEY"},
            )
        )
