from __future__ import annotations

import os

from fred_deepeval_cli.core.config_loader import load_configuration


def build_judge(config=None):
    from deepeval.models.llms import GPTModel, LiteLLMModel

    if config is None:
        config = load_configuration()

    profile = config.judge.active()
    provider = profile.provider
    model_name = profile.model
    settings = profile.settings

    if provider == "litellm":
        api_key_env = settings.api_key_env or "LITELLM_API_KEY"
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing {api_key_env} in environment/.env for the litellm judge."
            )
        return LiteLLMModel(
            model=model_name,
            api_key=api_key,
            base_url=settings.api_base,
            request_timeout=settings.request_timeout,
            num_retries=0,
        )

    if provider == "ollama":
        return LiteLLMModel(
            model=f"ollama/{model_name}",
            api_key="ollama",  # pragma: allowlist secret
            base_url=settings.api_base or "http://localhost:11434",
            request_timeout=settings.request_timeout,
            num_retries=0,
        )

    if provider == "openai":
        api_key_env = settings.api_key_env or "OPENAI_API_KEY"
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing {api_key_env} in environment/.env for the openai judge."
            )
        return GPTModel(model=model_name)

    raise ValueError(f"Unsupported judge provider: {provider}")
