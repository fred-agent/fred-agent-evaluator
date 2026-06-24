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
    from fred_evaluation_backend.workers.runner import _build_judge

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
    judge = _build_judge(judge_profile) if judge_profile is not None else None

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
        execution_grant=prep.execution_grant,
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

        # Fetch all case IDs — done in an activity to keep DB access outside the sandbox
        case_ids: list[str] = await workflow.execute_activity(
            fetch_campaign_cases,
            campaign_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        workflow.logger.info(
            "[CAMPAIGN-WORKFLOW] campaign=%s running %d cases", campaign_id, len(case_ids)
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
