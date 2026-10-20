"""KPI writer and Prometheus exporter, shared by the API and the worker.

Stream 1 of Fred's observability model: operational metrics scraped by Prometheus,
built from the same fred-core factory every other Fred backend uses.
"""

from __future__ import annotations

import logging

from fred_core.kpi import BaseKPIWriter, build_kpi_writer
from prometheus_client import start_http_server

from fred_evaluation_backend.config.models import EvaluationConfig

logger = logging.getLogger(__name__)


def start_kpi(configuration: EvaluationConfig, *, service_name: str) -> BaseKPIWriter:
    """Build the process KPI writer and serve `/metrics` when Prometheus is enabled."""
    kpi_writer = build_kpi_writer(
        kpi_config=configuration.observability.kpi,
        opensearch_config=configuration.storage.opensearch,
        service_name=service_name,
        log_level=configuration.app.log_level,
    )
    prometheus = configuration.observability.kpi.prometheus
    if prometheus.enabled:
        _ = start_http_server(prometheus.port, addr=prometheus.address)
        logger.info(
            "[%s] Prometheus metrics exporter ready at %s:%s",
            service_name,
            prometheus.address,
            prometheus.port,
        )
    return kpi_writer
