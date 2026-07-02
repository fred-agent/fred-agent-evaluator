from __future__ import annotations

from typing import Literal

from fred_core import SecurityConfiguration
from fred_core.common import KpiObservabilityConfig, ModelConfiguration
from fred_core.common.structures import (
    OpenSearchStoreConfig,
    PostgresStoreConfig,
    TemporalSchedulerConfig,
)
from fred_core.scheduler import SchedulerBackend
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    name: str = "Fred Evaluation Backend"
    base_url: str = "/evaluation/v1"
    address: str = "127.0.0.1"
    port: int = 8336
    log_level: str = "info"
    gcu_version: str | None = None


class ControlPlaneConfig(BaseModel):
    base_url: str = "http://localhost:8222/control-plane/v1"
    # Base URL used to resolve relative evaluate_url paths returned by prepare-execution.
    # In prod this is empty (ingress handles routing). In local dev, set to http://localhost:8000.
    runtime_base_url: str = ""
    # Base URL of the runtime app that serves the history capture endpoint
    # (`/agents/{id}/history`). Unlike runtime_base_url (host only, for resolving
    # relative evaluate_url paths), this must include the runtime app's path prefix
    # (e.g. http://localhost:8000/fred/agents/v2). Kept separate so capture and
    # campaign execution can use different bases without conflict.
    runtime_history_base_url: str = ""


class StorageConfig(BaseModel):
    postgres: PostgresStoreConfig = Field(default_factory=PostgresStoreConfig)
    opensearch: OpenSearchStoreConfig | None = None


class LangfuseObservabilityConfig(BaseModel):
    # Non-secret Langfuse settings; credentials come from the environment
    # (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY), per the Fred convention.
    host: str = "http://localhost:3001"


class ObservabilityConfig(BaseModel):
    # Mirrors fred-runtime's PodObservabilityConfig shape: a tracer backend
    # selector, Langfuse connection settings, and the shared KPI sink config.
    tracer: Literal["null", "logging", "langfuse"] = "logging"
    langfuse: LangfuseObservabilityConfig = Field(
        default_factory=LangfuseObservabilityConfig
    )
    kpi: KpiObservabilityConfig = Field(default_factory=KpiObservabilityConfig)


class WorkerConfig(BaseModel):
    max_concurrent_cases: int = 4
    poll_interval_seconds: int = 5
    # Judge models follow fred's canonical ModelConfiguration (provider / name /
    # settings). Switching provider/model is config-only; building the DeepEval
    # model is delegated to fred_evaluation_backend.model.factory.build_judge_model.
    judge_profiles: dict[str, ModelConfiguration] = Field(default_factory=dict)


class SchedulerConfig(BaseModel):
    backend: SchedulerBackend = SchedulerBackend.MEMORY
    temporal: TemporalSchedulerConfig = TemporalSchedulerConfig(task_queue="evaluation")


def _default_analysis() -> ModelConfiguration:
    """Provider-agnostic default for the campaign analysis model.

    Same schema as the judge (`provider` / `name` / `settings`) so the analysis
    is built by the shared `build_judge_model` factory. Kept as a separate config
    block so the analysis model can differ from the scoring model.
    """
    return ModelConfiguration(
        provider="litellm",
        name="mistral/mistral-small-latest",
        settings={"api_key_env": "MISTRAL_API_KEY"},  # pragma: allowlist secret
    )


def _default_security() -> SecurityConfiguration:
    """Canonical Fred security defaults, scoped to the evaluator.

    Both flows are disabled by default so local dev runs without Keycloak; the
    deployed config (configuration_prod.yaml / Helm ConfigMap) enables them.
    """
    return SecurityConfiguration.model_validate(
        {
            "m2m": {
                "enabled": False,
                "realm_url": "http://localhost:8080/realms/app",
                "client_id": "fred-evaluation-worker",
                "secret_env_var": "KEYCLOAK_EVAL_WORKER_CLIENT_SECRET",  # nosec B105  # pragma: allowlist secret
            },
            "user": {
                "enabled": False,
                "realm_url": "http://localhost:8080/realms/app",
                "client_id": "app",
            },
            "authorized_origins": [],
            "rebac": None,
        }
    )


class EvaluationConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)
    security: SecurityConfiguration = Field(default_factory=_default_security)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    analysis: ModelConfiguration = Field(default_factory=_default_analysis)
