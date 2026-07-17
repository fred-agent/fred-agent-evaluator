"""Temporal workflow and activities for evaluation runs.

The workflow layer only orchestrates — it delegates all I/O and heavy work to
activities, which run outside the Temporal sandbox.

Why this separation:
- Temporal replays workflow code on worker restart to reconstruct state.
  Any non-deterministic code (DB calls, HTTP, time) must live in activities.
- Activities run exactly once per schedule and can be retried independently.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Payload dataclasses — plain data that crosses the Temporal boundary
# ---------------------------------------------------------------------------


@dataclass
class RunInput:
    run_id: str


@dataclass
class RunCaseInput:
    case_id: str
    run_id: str


# ---------------------------------------------------------------------------
# Activities — all I/O lives here, outside the workflow sandbox
# ---------------------------------------------------------------------------


@activity.defn(name="fetch_run_cases")
async def fetch_run_cases(run_id: str) -> list[str]:
    from fred_evaluation_backend.workers._activity_context import get_store

    cases = await get_store().list_cases_by_run(run_id, limit=10000)
    return [c.case_id for c in cases]


@activity.defn(name="run_case_for_run")
async def run_case_for_run(payload: RunCaseInput) -> None:
    """Execute and score one case of a Run — config read from the Run row."""
    import json
    import uuid

    from fred_deepeval_cli.core.models import CustomMetricSpec

    from fred_evaluation_backend.execution.outbound_auth import ServiceAuthentication
    from fred_evaluation_backend.model.factory import build_judge_model
    from fred_evaluation_backend.workers._activity_context import (
        get_agent_client,
        get_config,
        get_cp_client,
        get_store,
    )
    from fred_evaluation_backend.workers.activities import execute_and_score_case

    store = get_store()
    config = get_config()
    cp_client = get_cp_client()
    agent_client = get_agent_client()

    run = await store.get_run(payload.run_id)
    case = await store.get_case(payload.case_id)

    prep = await cp_client.prepare_managed_instance_execution(
        team_id=run.team_id,
        agent_instance_id=run.target_instance_id,
        auth=ServiceAuthentication(),
    )

    judge_profile = config.worker.judge_profiles.get(run.judge_profile_id)
    judge = build_judge_model(judge_profile) if judge_profile is not None else None

    custom_metrics = [
        CustomMetricSpec.model_validate(m)
        for m in json.loads(run.custom_metrics_json or "[]")
    ]

    await execute_and_score_case(
        case_id=case.case_id,
        run_id=payload.run_id,
        created_by=run.created_by,
        input=case.input,
        expected_output=case.expected_output,
        agent_id=run.target_agent_id,
        agent_instance_id=prep.agent_instance_id,
        session_id=str(uuid.uuid4()),
        evaluate_url=prep.evaluate_url,
        team_id=run.team_id,
        token_provider=cp_client.m2m_token_provider,
        profile=run.profile,
        judge=judge,
        custom_metrics=custom_metrics,
        store=store,
        agent_client=agent_client,
    )


@activity.defn(name="finalize_run")
async def finalize_run(run_id: str) -> None:
    """Compute aggregates for a Run and mark it completed."""

    from fred_evaluation_backend.workers._activity_context import get_store

    store = get_store()
    refreshed = await store.list_cases_by_run(run_id, limit=10000)

    completed = len([c for c in refreshed if c.status in ("completed", "error")])
    passed = len([c for c in refreshed if c.verdict == "passed"])
    failed = len([c for c in refreshed if c.verdict == "failed"])
    insufficient = len([c for c in refreshed if c.verdict == "insufficient"])
    exec_errors = len([c for c in refreshed if c.outcome == "execution_error"])
    scoring_errors = len([c for c in refreshed if c.scoring_errors_json is not None])

    run = await store.get_run(run_id)
    if failed > 0:
        verdict = "failed"
    elif insufficient >= (run.total_cases or 1) / 2:
        verdict = "inconclusive"
    else:
        verdict = "passed"

    import json

    all_metrics = await store.list_metrics_by_run(run_id)
    metric_scores: dict[str, list[float]] = {}
    for m in all_metrics:
        if m.score is not None:
            try:
                metric_scores.setdefault(m.name, []).append(float(m.score))
            except ValueError:
                pass
    metric_averages = {
        name: sum(scores) / len(scores) for name, scores in metric_scores.items()
    }

    await store.update_run_aggregates(
        run_id,
        completed_cases=completed,
        passed_cases=passed,
        failed_cases=failed,
        execution_error_cases=exec_errors,
        scoring_error_cases=scoring_errors,
        verdict=verdict,
        operational_state="completed",
        metric_averages_json=json.dumps(metric_averages) if metric_averages else None,
    )
    await store.create_run_event(run_id, kind="run_completed", payload_json=None)


@workflow.defn
class RunWorkflow:
    """Orchestrate one Run: fetch its cases, score them in parallel, finalize.

    Workflow ID = `run-eval-{run_id}` — one durable execution per Run.
    """

    @workflow.run
    async def run(self, payload: RunInput) -> None:
        run_id = payload.run_id
        workflow.logger.info("[RUN-WORKFLOW] starting run=%s", run_id)

        case_ids: list[str] = await workflow.execute_activity(
            fetch_run_cases,
            run_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        await asyncio.gather(
            *[
                workflow.execute_activity(
                    run_case_for_run,
                    RunCaseInput(case_id=case_id, run_id=run_id),
                    start_to_close_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                for case_id in case_ids
            ]
        )

        await workflow.execute_activity(
            finalize_run,
            run_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        workflow.logger.info("[RUN-WORKFLOW] run=%s done", run_id)
