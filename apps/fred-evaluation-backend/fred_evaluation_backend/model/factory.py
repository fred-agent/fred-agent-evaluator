"""Build a DeepEval judge model from a canonical `ModelConfiguration`.

Why this module exists:
- Mirrors the role of `fred_core/model/factory.py` (which builds LangChain models),
  but produces a **DeepEval** model — the two are not interchangeable, so we reuse
  fred's config *schema* (`ModelConfiguration`: provider / name / settings), not its
  factory code.
- Every model it builds calls through `judge_calls.CallPolicy` (bounded retries,
  rate cap, KPIs), whatever the provider.

How to use it:
- `judge = build_judge_model(config.worker.judge_profiles[profile_id], kpi=kpi)`
- Switching provider/model is config-only: change `provider` / `name` / `settings`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fred_core.common import ModelConfiguration
from fred_core.kpi import BaseKPIWriter, NoOpKPIWriter

from fred_evaluation_backend.config.models import validate_model_profile
from fred_evaluation_backend.model.judge_calls import CallPolicy, limiter_for

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


def _litellm_target(cfg: ModelConfiguration) -> tuple[str, str | None, str | None]:
    """Resolve (litellm model id, api key, base url) for a provider.

    - ``litellm``    — provider-agnostic; `name` carries the `provider/model` prefix
      (e.g. ``mistral/mistral-small-latest``, or ``openai/<model>`` with
      ``settings.base_url`` for any OpenAI-compatible endpoint).
    - ``vertex_ai``  — Google Vertex AI via Application Default Credentials (Workload
      Identity), no API key. `name` is the bare model (e.g. ``gemini-2.5-flash``);
      project/region come from the ``VERTEXAI_PROJECT`` / ``VERTEXAI_LOCATION`` env.
    - ``ollama``     — local models via litellm's ollama routing.
    """
    provider = (cfg.provider or "").lower()
    name = cfg.name or ""
    settings: dict[str, Any] = cfg.settings or {}
    base_url = _setting(settings, "base_url", "api_base")

    if provider == "litellm":
        return name, _require_api_key(settings, "LITELLM_API_KEY"), base_url
    if provider in ("vertex_ai", "vertex"):
        # Keyless on GKE (Workload Identity), like knowledge-flow and fred-agents, so
        # the judge stays inside the platform. DeepEval tolerates a null key.
        model = name if name.startswith("vertex_ai/") else f"vertex_ai/{name}"
        return model, None, base_url
    if provider == "ollama":
        api_key = "ollama"  # pragma: allowlist secret
        return f"ollama/{name}", api_key, base_url or "http://localhost:11434"
    raise ValueError(f"Unsupported judge provider: {cfg.provider!r}")


def build_judge_model(
    cfg: ModelConfiguration,
    *,
    role: str = "judge",
    kpi: BaseKPIWriter | None = None,
):
    """Map a `ModelConfiguration` to a bounded DeepEval model.

    `role` is the `llm_role` KPI label: ``judge`` for scoring, ``analysis`` for the
    run analysis.
    """
    from fred_evaluation_backend.model.bounded_model import BoundedLiteLLMModel

    limits = validate_model_profile(cfg.name or "", cfg)
    model, api_key, base_url = _litellm_target(cfg)
    policy = CallPolicy(
        model_name=model,
        role=role,
        max_attempts=limits.max_attempts,
        limiter=limiter_for(
            (cfg.provider or "").lower(), model, limits.max_calls_per_minute
        ),
        kpi=kpi or NoOpKPIWriter(),
    )
    return BoundedLiteLLMModel(
        call_policy=policy,
        model=model,
        api_key=api_key,
        base_url=base_url,
        request_timeout=limits.request_timeout,
    )
