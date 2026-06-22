from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

_TRACER_NAME = "fred-evaluation"


def setup_otel(endpoint: str, public_key_env: str, secret_key_env: str) -> bool:
    """Initialize OTel TracerProvider with OTLP exporter toward Langfuse.

    Args:
        endpoint: OTLP base URL (e.g. http://localhost:3030)
        public_key_env: env var name holding the Langfuse public key
        secret_key_env: env var name holding the Langfuse secret key

    Returns True if OTel was configured, False if keys are missing.
    """
    public_key = os.environ.get(public_key_env, "")
    secret_key = os.environ.get(secret_key_env, "")

    if not public_key or not secret_key:
        logger.info("[OTEL] %s/%s not set — tracing disabled", public_key_env, secret_key_env)
        return False

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    otlp_endpoint = endpoint.rstrip("/") + "/api/public/otel/v1/traces"
    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}

    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, headers=headers)
    provider = TracerProvider(
        resource=Resource.create({"service.name": "fred-evaluation-worker"})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info("[OTEL] tracing enabled → %s", otlp_endpoint)
    return True


def get_tracer():
    from opentelemetry import trace
    return trace.get_tracer(_TRACER_NAME)
