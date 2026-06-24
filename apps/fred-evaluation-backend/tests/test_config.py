"""Configuration contract tests.

These lock in the canonical Fred config shape for the evaluation backend so that
a stray merge (built on an older config) cannot silently revert it: the top-level
sections must stay `app` / `storage.postgres` / `security` (fred-core
SecurityConfiguration with m2m+user) / `observability` (tracer/langfuse/kpi) /
`scheduler` (fred-core backend + temporal) / `worker`, with no bespoke
`telemetry:` or top-level `database:` keys.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from fred_evaluation_backend.config.models import EvaluationConfig
from fred_evaluation_backend.execution.auth import build_m2m_token_provider

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _load(name: str) -> EvaluationConfig:
    payload = yaml.safe_load((_CONFIG_DIR / name).read_text())
    return EvaluationConfig.model_validate(payload)


def test_default_config_has_canonical_shape() -> None:
    cfg = EvaluationConfig()
    # Canonical sections present.
    assert cfg.storage.postgres is not None
    assert cfg.security.m2m is not None and cfg.security.user is not None
    assert cfg.observability.tracer in ("null", "logging", "langfuse")
    assert cfg.observability.langfuse.host
    assert cfg.scheduler.temporal.task_queue == "evaluation"
    # Bespoke / pre-convergence fields must NOT exist.
    assert not hasattr(cfg, "telemetry")
    assert not hasattr(cfg, "database")


def test_dev_configuration_parses_and_is_canonical() -> None:
    cfg = _load("configuration.yaml")
    assert cfg.storage.postgres.sqlite_path  # dev uses SQLite
    assert cfg.security.m2m.client_id == "evaluation"
    assert cfg.security.m2m.secret_env_var == "KEYCLOAK_EVALUATION_CLIENT_SECRET"
    assert cfg.observability.tracer == "langfuse"
    assert cfg.observability.langfuse.host == "http://localhost:3001"


def test_prod_configuration_parses_and_is_canonical() -> None:
    cfg = _load("configuration_prod.yaml")
    assert cfg.storage.postgres.database == "evaluation"
    assert cfg.storage.postgres.username == "evaluation"
    assert cfg.security.user.enabled is True
    assert cfg.security.m2m.enabled is True
    assert cfg.scheduler.temporal.task_queue == "evaluation"


def test_m2m_token_provider_disabled_returns_none() -> None:
    cfg = EvaluationConfig()  # m2m disabled by default
    assert build_m2m_token_provider(cfg.security) is None
