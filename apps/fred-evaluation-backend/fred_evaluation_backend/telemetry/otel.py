from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

_TRACER_NAME = "fred-evaluation"


def setup_otel(host: str) -> bool:
    """Initialize OTel TracerProvider with OTLP exporter toward Langfuse.

    Credentials follow the Fred convention: they are read from the canonical
    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY environment variables. The Langfuse
    host comes from observability.langfuse.host.

    Args:
        host: Langfuse base URL (e.g. http://localhost:3001)

    Returns True if OTel was configured, False if keys are missing.
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not public_key or not secret_key:
        logger.info(
            "[OTEL] LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set — tracing disabled"
        )
        return False

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    otlp_endpoint = host.rstrip("/") + "/api/public/otel/v1/traces"
    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}

    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        headers=headers,
        timeout=30,
    )
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
