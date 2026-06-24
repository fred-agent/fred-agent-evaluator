from __future__ import annotations

from fred_core import SecurityConfiguration
from fred_core.common import KpiObservabilityConfig
from fred_core.common.structures import OpenSearchStoreConfig, PostgresStoreConfig
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    name: str = "Fred Evaluation Backend"
    base_url: str = "/evaluation/v1"
    address: str = "127.0.0.1"
    port: int = 8333
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


class ObservabilityConfig(BaseModel):
    kpi: KpiObservabilityConfig = Field(default_factory=KpiObservabilityConfig)


class JudgeProfileSettings(BaseModel):
    api_key_env: str | None = None
    api_base: str | None = None
    request_timeout: int = 30


class JudgeProfile(BaseModel):
    provider: str  # litellm | openai | ollama
    model: str
    settings: JudgeProfileSettings = Field(default_factory=JudgeProfileSettings)


class WorkerConfig(BaseModel):
    max_concurrent_cases: int = 4
    poll_interval_seconds: int = 5
    judge_profiles: dict[str, JudgeProfile] = Field(default_factory=dict)


class AnalysisConfig(BaseModel):
    api_key_env: str = "MISTRAL_API_KEY"
    model: str = "mistral-small-latest"
    base_url: str = "https://api.mistral.ai/v1"


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
                "client_id": "evaluation",
                "secret_env_var": "KEYCLOAK_EVALUATION_CLIENT_SECRET",  # nosec B105
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
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
