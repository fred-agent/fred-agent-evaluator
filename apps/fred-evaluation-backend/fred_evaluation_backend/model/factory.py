"""Build a DeepEval judge model from a canonical `ModelConfiguration`.

Why this module exists:
- Mirrors the role of `fred_core/model/factory.py` (which builds LangChain models),
  but produces a **DeepEval** model — the two are not interchangeable, so we reuse
  fred's config *schema* (`ModelConfiguration`: provider / name / settings), not its
  factory code.
- Keeps model-building logic out of the worker/runner (separation of concerns).

How to use it:
- `judge = build_judge_model(config.worker.judge_profiles[profile_id])`
- Switching provider/model is config-only: change `provider` / `name` / `settings`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fred_core.common import ModelConfiguration

logger = logging.getLogger(__name__)


def _setting(settings: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present key among `keys` from a settings dict."""
    for key in keys:
        if key in settings and settings[key] is not None:
            return settings[key]
    return default


def _require_api_key(settings: dict[str, Any], default_env: str) -> str:
    api_key_env = _setting(settings, "api_key_env", default=default_env)
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing {api_key_env} in environment for judge model.")
    return api_key


def build_judge_model(cfg: ModelConfiguration):
    """Map a `ModelConfiguration` to a DeepEval model instance.

    Supported providers:
    - ``litellm``    — provider-agnostic; `name` carries the `provider/model` prefix
      (e.g. ``mistral/mistral-small-latest``). Preferred for keyed providers.
    - ``vertex_ai``  — Google Vertex AI via Application Default Credentials (Workload
      Identity), no API key. `name` is the bare model (e.g. ``gemini-2.5-flash``);
      project/region come from the ``VERTEXAI_PROJECT`` / ``VERTEXAI_LOCATION`` env.
    - ``ollama``     — local models via litellm's ollama routing.
    - ``openai``     — OpenAI or any OpenAI-compatible endpoint (set `settings.base_url`).
    """
    from deepeval.models.llms import LiteLLMModel

    provider = (cfg.provider or "").lower()
    name = cfg.name or ""
    settings: dict[str, Any] = cfg.settings or {}
    base_url = _setting(settings, "base_url", "api_base")
    request_timeout = _setting(settings, "request_timeout", default=30)

    if provider == "litellm":
        return LiteLLMModel(
            model=name,
            api_key=_require_api_key(settings, "LITELLM_API_KEY"),
            base_url=base_url,
            request_timeout=request_timeout,
            num_retries=0,
        )

    if provider in ("vertex_ai", "vertex"):
        # Google Vertex AI, authenticated by Application Default Credentials — on GKE
        # that is Workload Identity (the pod's service account), NOT an API key. This
        # matches how knowledge-flow and fred-agents reach Vertex, so the evaluator judge
        # stays inside the platform (no external egress, no Mistral/OpenAI key).
        #
        # litellm routes the `vertex_ai/<model>` prefix and reads the project + region
        # from the VERTEXAI_PROJECT / VERTEXAI_LOCATION env vars (set on the Deployment).
        # `name` may be bare ("gemini-2.5-flash") or already prefixed ("vertex_ai/...").
        model = name if name.startswith("vertex_ai/") else f"vertex_ai/{name}"
        return LiteLLMModel(
            model=model,
            api_key=None,  # ADC / Workload Identity — deepeval tolerates a null key
            base_url=base_url,
            request_timeout=request_timeout,
            num_retries=0,
        )

    if provider == "ollama":
        return LiteLLMModel(
            model=f"ollama/{name}",
            api_key="ollama",  # pragma: allowlist secret
            base_url=base_url or "http://localhost:11434",
            request_timeout=request_timeout,
            num_retries=0,
        )

    if provider == "openai":
        from deepeval.models.llms import GPTModel

        api_key = _require_api_key(settings, "OPENAI_API_KEY")
        # GPTModel uses the raw OpenAI SDK: pass api_key + base_url so an
        # OpenAI-compatible endpoint is used, and strip any litellm-style
        # "provider/" prefix (the SDK expects the bare model name).
        model_name = name.split("/", 1)[-1] if "/" in name else name
        return GPTModel(model=model_name, api_key=api_key, base_url=base_url)

    raise ValueError(f"Unsupported judge provider: {cfg.provider!r}")
