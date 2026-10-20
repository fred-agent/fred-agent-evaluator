from __future__ import annotations

from typing import ClassVar, Literal

from fred_core import LogStorageConfig, SecurityConfiguration
from fred_core.common import KpiObservabilityConfig, ModelConfiguration
from fred_core.common.structures import (
    OpenSearchStoreConfig,
    PostgresStoreConfig,
    TemporalSchedulerConfig,
)
from fred_core.scheduler import SchedulerBackend
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SUPPORTED_MODEL_PROVIDERS = ("litellm", "vertex_ai", "vertex", "ollama")


class ModelCallSettings(BaseModel):
    """Load limits a model profile may set in its `settings`, with their defaults.

    Per process: N worker replicas make N × `max_calls_per_minute`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    max_attempts: int = Field(default=2, ge=1)
    request_timeout: float = Field(default=60, ge=1)
    max_calls_per_minute: int = Field(default=60, ge=1)


def validate_model_profile(label: str, cfg: ModelConfiguration) -> ModelCallSettings:
    """Reject a profile the evaluator cannot call, naming the profile."""
    provider = (cfg.provider or "").lower()
    if provider == "openai":
        raise ValueError(
            f"model profile '{label}': provider 'openai' is no longer supported; "
            "use provider 'litellm' with name 'openai/<model>' and settings.base_url"
        )
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ValueError(
            f"model profile '{label}': unsupported provider {cfg.provider!r}; "
            f"expected one of {', '.join(SUPPORTED_MODEL_PROVIDERS)}"
        )
    try:
        return ModelCallSettings.model_validate(cfg.settings or {})
    except ValidationError as exc:
        fields = ", ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        raise ValueError(
            f"model profile '{label}': invalid settings ({fields})"
        ) from exc


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


class StorageConfig(BaseModel):
    postgres: PostgresStoreConfig = Field(default_factory=PostgresStoreConfig)
    opensearch: OpenSearchStoreConfig | None = None
    # Stream 4 of docs/swift/platform/OBSERVABILITY-AND-AUDIT.md §6: generic
    # diagnostic logs. `opensearch` makes them durable and explorable from
    # OpenSearch Dashboards; absent, fred-core falls back to a bounded in-memory
    # ring, which is fine for local dev and is not a durability guarantee.
    log_store: LogStorageConfig | None = None


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
    # Serial by default. Every case is a real agent turn against a live runtime and a
    # judge LLM, so concurrency here is a burst against someone else's rate limits, not
    # a local speed dial. Raise it deliberately once the target is known to absorb it.
    # This is the single lever for both execution paths: the in-memory runner's
    # semaphore and, for Temporal, `max_concurrent_activities` (see main_worker.py).
    max_concurrent_cases: int = 1
    poll_interval_seconds: int = 5
    # Judge models follow fred's canonical ModelConfiguration (provider / name /
    # settings). Switching provider/model is config-only; building the DeepEval
    # model is delegated to fred_evaluation_backend.model.factory.build_judge_model.
    judge_profiles: dict[str, ModelConfiguration] = Field(default_factory=dict)


class SchedulerConfig(BaseModel):
    backend: SchedulerBackend = SchedulerBackend.MEMORY
    temporal: TemporalSchedulerConfig = TemporalSchedulerConfig(task_queue="evaluation")


def _default_analysis() -> ModelConfiguration:
    """Provider-agnostic default for the run analysis model.

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

    `user` is consumed by the API (interactive requests propagate the caller's
    own JWT); `m2m` is consumed by the worker only, for its own
    `fred-evaluation-worker` service identity (RFC EVAL-AUTH). The API and
    worker load this same config shape, but `main.py` never builds an M2M
    client from the `m2m` block.
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

    @model_validator(mode="after")
    def _model_profiles_are_callable(self) -> "EvaluationConfig":
        # At load, not per case: a bad profile would otherwise fail every case of a run.
        for profile_id, profile in self.worker.judge_profiles.items():
            _ = validate_model_profile(profile_id, profile)
        _ = validate_model_profile("analysis", self.analysis)
        return self
