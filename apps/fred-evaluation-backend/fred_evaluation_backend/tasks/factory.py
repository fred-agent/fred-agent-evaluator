from __future__ import annotations

from fastapi import Request
from fred_core.scheduler import SchedulerBackend, TemporalClientProvider
from fred_core.tasks.service import TaskService
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.config.models import EvaluationConfig


def build_task_service(
    configuration: EvaluationConfig, engine: AsyncEngine
) -> TaskService:
    """Build the shared task-event bus service (``fred_core.tasks``) for the evaluator.

    EVAL-02: campaigns are driven as bus tasks (kind ``evaluation``) through the SAME
    task-event bus + scheduler abstraction used by control-plane and knowledge-flow,
    instead of the bespoke polling runner + private event store. Mirrors the
    knowledge-flow ``TaskService`` wiring.

    With the TEMPORAL backend the bus persists events in Postgres and reconciles task
    state against the durable Temporal executor; with MEMORY it runs an in-process bus
    with a no-op executor (light local dev only).
    """
    backend = configuration.scheduler.backend
    temporal_provider = (
        TemporalClientProvider(configuration.scheduler.temporal)
        if backend == SchedulerBackend.TEMPORAL
        else None
    )
    return TaskService.build(
        engine=engine,
        backend=backend,
        temporal_client_provider=temporal_provider,
        postgres_dsn=configuration.storage.postgres.dsn()
        if backend == SchedulerBackend.TEMPORAL
        else None,
    )


def get_task_service(request: Request) -> TaskService:
    """FastAPI dependency: the shared task-event bus service from app state."""
    return request.app.state.task_service
