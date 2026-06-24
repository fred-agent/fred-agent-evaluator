from __future__ import annotations

import asyncio
import logging

from fred_core import log_setup
from fred_core.logs.null_log_store import NullLogStore
from fred_core.scheduler import SchedulerBackend
from fred_core.sql import create_async_engine_from_config

from fred_evaluation_backend.campaigns.store import EvaluationStore
from fred_evaluation_backend.config.loader import load_configuration
from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.execution.auth import build_m2m_token_provider
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.telemetry.otel import setup_otel
from fred_evaluation_backend.workers.runner import CampaignRunner

logger = logging.getLogger(__name__)


async def _run_temporal_worker(configuration, engine, cp_client) -> None:
    import concurrent.futures

    from temporalio.client import Client
    from temporalio.worker import Worker
    from temporalio.worker.workflow_sandbox import (
        SandboxedWorkflowRunner,
        SandboxRestrictions,
    )

    from fred_evaluation_backend.workers import _activity_context
    from fred_evaluation_backend.workers.workflow import (
        CampaignWorkflow,
        fetch_campaign_cases,
        finalize_campaign,
        run_case,
    )

    store = EvaluationStore(engine)
    agent_client = AgentClient()

    _activity_context.init(
        store=store,
        config=configuration,
        agent_client=agent_client,
        cp_client=cp_client,
    )

    temporal_cfg = configuration.scheduler.temporal
    logger.info(
        "Connecting to Temporal at %s (namespace=%s, queue=%s)",
        temporal_cfg.host,
        temporal_cfg.namespace,
        temporal_cfg.task_queue,
    )
    client = await Client.connect(
        target_host=temporal_cfg.host,
        namespace=temporal_cfg.namespace,
    )

    max_concurrent = configuration.worker.max_concurrent_cases
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent)
    worker = Worker(
        client=client,
        task_queue=temporal_cfg.task_queue,
        workflows=[CampaignWorkflow],
        activities=[fetch_campaign_cases, run_case, finalize_campaign],
        activity_executor=executor,
        max_concurrent_activities=max_concurrent,
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules("rich")
        ),
    )

    logger.info("Temporal evaluation worker ready.")
    await worker.run()


async def main() -> None:
    configuration = load_configuration()
    log_setup(
        service_name="fred-evaluation-worker",
        log_level=configuration.app.log_level,
        store=NullLogStore(),
    )
    logger.info("Fred evaluation worker starting...")
    if configuration.observability.tracer == "langfuse":
        setup_otel(host=configuration.observability.langfuse.host)

    engine = create_async_engine_from_config(configuration.storage.postgres)
    token_provider = build_m2m_token_provider(configuration.security)
    cp_client = ControlPlaneClient(
        base_url=configuration.control_plane.base_url,
        token_provider=token_provider,
        runtime_base_url=configuration.control_plane.runtime_base_url,
    )

    backend = configuration.scheduler.backend
    if backend == SchedulerBackend.TEMPORAL:
        logger.info("Scheduler backend: TEMPORAL")
        await _run_temporal_worker(configuration, engine, cp_client)
    else:
        logger.info("Scheduler backend: MEMORY (asyncio polling)")
        runner = CampaignRunner(
            config=configuration, engine=engine, cp_client=cp_client
        )
        await runner.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
