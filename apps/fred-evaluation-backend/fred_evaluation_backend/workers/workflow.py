"""Temporal workflow and activities for campaign evaluation.

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
class CampaignInput:
    campaign_id: str


@dataclass
class CaseInput:
    case_id: str
    campaign_id: str


# ---------------------------------------------------------------------------
# Activities — all I/O lives here, outside the workflow sandbox
# ---------------------------------------------------------------------------


async def _publish(campaign_id: str, state, *, progress: float, detail_counts: dict):
    """Publish one campaign lifecycle event on the shared task bus (EVAL-02).

    Only two callers, and that is deliberate: ``record_event`` reads ``task_run.seq``
    and writes ``seq + 1`` without locking the row, while ``task_event_log`` carries a
    ``UNIQUE (task_id, seq)`` constraint. Two writers on the *same* task would collide.
    Knowledge-flow escapes this by minting one task per file; a campaign is one task, so
    we may only publish where a single writer exists — before the cases fan out, and
    after they have all joined. Never from ``run_case``, which runs in parallel.

    A campaign created before EVAL-02 has no bus task; publishing is then a no-op.
    """
    from datetime import datetime, timezone

    from fred_core.tasks import EvaluationDetail, EvaluationTaskEvent

    from fred_evaluation_backend.workers._activity_context import (
        get_store,
        get_task_service,
    )

    campaign = await get_store().get_campaign(campaign_id)
    if campaign is None or not campaign.task_id:
        return

    await get_task_service().record(
        EvaluationTaskEvent(
            task_id=campaign.task_id,
            state=state,
            seq=0,  # reassigned by record()
            timestamp=datetime.now(timezone.utc),
            progress=progress,
            owner=campaign.created_by,
            detail=EvaluationDetail(campaign_id=campaign_id, **detail_counts),
        )
    )


@activity.defn(name="mark_campaign_running")
async def mark_campaign_running(campaign_id: str) -> None:
    """Announce the campaign has started, before the cases fan out.

    Without this the bus task stays ``pending`` for the whole run, so the task tray
    shows nothing moving even though the workflow is well under way.
    """
    from fred_core.tasks import TaskState

    from fred_evaluation_backend.workers._activity_context import get_store

    campaign = await get_store().get_campaign(campaign_id)
    total = campaign.total_cases if campaign else 0
    await _publish(
        campaign_id,
        TaskState.running,
        progress=0.0,
        detail_counts=dict(
            completed=0,
            total=total,
            passed=0,
            failed=0,
            execution_errors=0,
            scoring_errors=0,
        ),
    )


@activity.defn(name="fetch_campaign_cases")
async def fetch_campaign_cases(campaign_id: str) -> list[str]:
    """Return the list of case_ids for a campaign."""
    from fred_evaluation_backend.campaigns.store import EvaluationStore
    from fred_evaluation_backend.workers._activity_context import get_store

    store: EvaluationStore = get_store()
    cases = await store.list_cases_by_campaign(campaign_id, limit=10000)
    return [c.case_id for c in cases]


@activity.defn(name="run_case")
async def run_case(payload: CaseInput) -> None:
    """Execute and score one evaluation case."""
    import uuid

    from fred_evaluation_backend.workers._activity_context import (
        get_agent_client,
        get_config,
        get_cp_client,
        get_store,
    )
    from fred_evaluation_backend.workers.activities import execute_and_score_case
    from fred_evaluation_backend.model.factory import build_judge_model

    store = get_store()
    config = get_config()
    cp_client = get_cp_client()
    agent_client = get_agent_client()

    campaign = await store.get_campaign(payload.campaign_id)
    case = await store.get_case(payload.case_id)

    if campaign.target_kind == "runtime_agent":
        prep = await cp_client.prepare_runtime_agent_execution(
            team_id=campaign.team_id,
            runtime_id=campaign.target_runtime_id,
            agent_id=campaign.target_agent_id,
        )
    else:
        prep = await cp_client.prepare_managed_instance_execution(
            team_id=campaign.team_id,
            agent_instance_id=campaign.target_instance_id,
        )

    judge_profile = config.worker.judge_profiles.get(campaign.judge_profile_id)
    judge = build_judge_model(judge_profile) if judge_profile is not None else None

    await execute_and_score_case(
        case_id=case.case_id,
        campaign_id=payload.campaign_id,
        created_by=campaign.created_by,
        input=case.input,
        expected_output=case.expected_output,
        agent_id=campaign.target_agent_id,
        agent_instance_id=prep.agent_instance_id
        if campaign.target_kind == "managed_instance"
        else None,
        session_id=str(uuid.uuid4()),
        evaluate_url=prep.evaluate_url,
        team_id=campaign.team_id,
        token_provider=cp_client._token_provider,
        profile=campaign.profile,
        judge=judge,
        store=store,
        agent_client=agent_client,
    )


@activity.defn(name="finalize_campaign")
async def finalize_campaign(campaign_id: str) -> None:
    """Compute aggregates and mark the campaign as completed."""
    import json

    from fred_evaluation_backend.workers._activity_context import get_store

    store = get_store()
    refreshed = await store.list_cases_by_campaign(campaign_id, limit=10000)

    completed = len([c for c in refreshed if c.status in ("completed", "error")])
    passed = len([c for c in refreshed if c.verdict == "passed"])
    failed = len([c for c in refreshed if c.verdict == "failed"])
    insufficient = len([c for c in refreshed if c.verdict == "insufficient"])
    exec_errors = len([c for c in refreshed if c.outcome == "execution_error"])
    scoring_errors = len([c for c in refreshed if c.scoring_errors_json is not None])

    campaign = await store.get_campaign(campaign_id)
    if failed > 0:
        verdict = "failed"
    elif insufficient >= campaign.total_cases / 2:
        verdict = "insufficient"
    else:
        verdict = "passed"

    all_metrics = await store.list_metrics_by_campaign(campaign_id)
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

    await store.update_campaign_aggregates(
        campaign_id,
        completed_cases=completed,
        passed_cases=passed,
        failed_cases=failed,
        execution_error_cases=exec_errors,
        scoring_error_cases=scoring_errors,
        verdict=verdict,
        operational_state="completed",
        metric_averages_json=json.dumps(metric_averages) if metric_averages else None,
    )
    await store.create_event(campaign_id, kind="campaign_completed", payload_json=None)

    # EVAL-02: the cases have all joined, so this is the second (and last) single-writer
    # moment. `succeeded` here means "the campaign ran to the end", not "the agent scored
    # well" — the business outcome is `verdict`, above, and a poor score must not look
    # like a broken run. Without this publish the sweeper later finds a workflow Temporal
    # calls completed whose task never reported success, and marks the task `failed`.
    from fred_core.tasks import TaskState

    await _publish(
        campaign_id,
        TaskState.succeeded,
        progress=1.0,
        detail_counts=dict(
            completed=completed,
            total=campaign.total_cases,
            passed=passed,
            failed=failed,
            execution_errors=exec_errors,
            scoring_errors=scoring_errors,
        ),
    )


# ---------------------------------------------------------------------------
# Workflow — orchestration only, no I/O
# ---------------------------------------------------------------------------


@workflow.defn
class CampaignWorkflow:
    """Orchestrate the evaluation of all cases in one campaign.

    Why one workflow per campaign:
    - Each campaign appears as a named, filterable entry in the Temporal UI.
    - Workflow ID = `campaign-eval-{campaign_id}` — visible and queryable.
    - Individual case failures don't abort the campaign; the workflow retries
      the failing activity independently.
    """

    @workflow.run
    async def run(self, payload: CampaignInput) -> None:
        campaign_id = payload.campaign_id
        workflow.logger.info("[CAMPAIGN-WORKFLOW] starting campaign=%s", campaign_id)

        # EVAL-02: announce the start on the shared bus, while this is still the only
        # writer on the task. Once the cases fan out below, nothing may publish.
        await workflow.execute_activity(
            mark_campaign_running,
            campaign_id,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Fetch all case IDs — done in an activity to keep DB access outside the sandbox
        case_ids: list[str] = await workflow.execute_activity(
            fetch_campaign_cases,
            campaign_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        workflow.logger.info(
            "[CAMPAIGN-WORKFLOW] campaign=%s running %d cases",
            campaign_id,
            len(case_ids),
        )

        # Run all cases in parallel — each case is an independent activity
        await asyncio.gather(
            *[
                workflow.execute_activity(
                    run_case,
                    CaseInput(case_id=case_id, campaign_id=campaign_id),
                    start_to_close_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                for case_id in case_ids
            ]
        )

        # Compute aggregates and mark campaign done
        await workflow.execute_activity(
            finalize_campaign,
            campaign_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        workflow.logger.info("[CAMPAIGN-WORKFLOW] campaign=%s done", campaign_id)
