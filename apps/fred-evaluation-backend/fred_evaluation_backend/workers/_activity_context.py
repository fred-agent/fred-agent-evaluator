"""Module-level singletons injected by the worker process at startup.

Why this pattern:
- Temporal activities are plain functions — they can't receive dependencies via
  constructor injection.
- Passing non-serializable objects (DB engine, HTTP clients) through Temporal
  workflow parameters is forbidden (Temporal serializes all payloads to JSON).
- The worker process initializes these singletons once before starting the
  Temporal worker, so all activity invocations share the same instances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fred_evaluation_backend.campaigns.store import EvaluationStore
    from fred_evaluation_backend.config.models import EvaluationConfig
    from fred_evaluation_backend.execution.agent_client import AgentClient
    from fred_evaluation_backend.execution.control_plane_client import (
        ControlPlaneClient,
    )

_store: "EvaluationStore | None" = None
_config: "EvaluationConfig | None" = None
_agent_client: "AgentClient | None" = None
_cp_client: "ControlPlaneClient | None" = None


def init(
    *,
    store: "EvaluationStore",
    config: "EvaluationConfig",
    agent_client: "AgentClient",
    cp_client: "ControlPlaneClient",
) -> None:
    global _store, _config, _agent_client, _cp_client
    _store = store
    _config = config
    _agent_client = agent_client
    _cp_client = cp_client


def get_store() -> "EvaluationStore":
    if _store is None:
        raise RuntimeError("Activity context not initialised — call init() first")
    return _store


def get_config() -> "EvaluationConfig":
    if _config is None:
        raise RuntimeError("Activity context not initialised — call init() first")
    return _config


def get_agent_client() -> "AgentClient":
    if _agent_client is None:
        raise RuntimeError("Activity context not initialised — call init() first")
    return _agent_client


def get_cp_client() -> "ControlPlaneClient":
    if _cp_client is None:
        raise RuntimeError("Activity context not initialised — call init() first")
    return _cp_client
