"""Temporal workflow and activities for evaluation runs.

The workflow layer only orchestrates — it delegates all I/O and heavy work to
activities, which run outside the Temporal sandbox.

Why this separation:
- Temporal replays workflow code on worker restart to reconstruct state.
  Any non-deterministic code (DB calls, HTTP, time) must live in activities.
- Activities run exactly once per schedule and can be retried independently.

Terminal-state guarantee (EVAL — runs-list progress + failure visibility):
- The Run row's own `operational_state`/`completed_cases` fields are what the
  runs-list UI polls (it does not read case rows directly). Every path
  through this workflow — full success, some cases failing, or the workflow
  itself blowing up before a single case could run — must leave that row in
  a state that reflects reality:
    * `mark_run_started` flips `pending` -> `running` before any case runs,
      so the list shows the run as in-progress instead of still `pending`.
    * `run_case_for_run` refreshes the Run's aggregate counters after *each*
      case, so `completed_cases` genuinely increments as cases finish
      instead of jumping from 0 to N only once the whole run is done.
    * `finalize_run` always runs last and sets the terminal `completed`
      state (business pass/fail lives in `verdict`, not `operational_state`
      — a run that executed but whose cases failed is still `completed`).
    * If anything above raises after retries are exhausted (e.g.
      `fetch_run_cases` can't reach the DB, or `finalize_run` itself fails),
      the workflow's except clause calls `mark_run_failed` so the Run row
      still reaches a terminal state, then re-raises so Temporal's own
      workflow status reflects the failure too.
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
# Shared aggregate helper — one definition of "how do we count a run's cases",
# reused by the per-case progress update and the final run summary so the two
# views can never drift apart.
# ---------------------------------------------------------------------------


@dataclass
class CaseAggregates:
    completed: int
    passed: int
    failed: int
    execution_errors: int
    scoring_errors: int


def summarize_cases(cases) -> CaseAggregates:
    """Tally one Run's case rows into the aggregate counters stored on the Run.

    Why this exists: both the per-case progress update (fired after every
    case finishes) and the end-of-run summary (`finalize_run`) need the
    exact same counting rules. A previous version duplicated this logic in
    two places; keeping one implementation means the runs-list progress and
    the run detail page can never show different completed counts.
    """
    return CaseAggregates(
        completed=len([c for c in cases if c.status in ("completed", "error")]),
        passed=len([c for c in cases if c.verdict == "passed"]),
        failed=len([c for c in cases if c.verdict == "failed"]),
        execution_errors=len([c for c in cases if c.outcome == "execution_error"]),
        scoring_errors=len([c for c in cases if c.scoring_errors_json is not None]),
    )


# ---------------------------------------------------------------------------
# Activities — all I/O lives here, outside the workflow sandbox
# ---------------------------------------------------------------------------


@activity.defn(name="mark_run_started")
async def mark_run_started(run_id: str) -> None:
    """Flip a Run from `pending` to `running` before any case executes.

    Why this exists: the runs-list UI polls the Run row's own
    `operational_state` (via the canonical task-state mapping in
    `tasks/models.py::map_state`). Without this activity nothing wrote to
    the row until `finalize_run` ran at the very end, so the list showed
    `pending` for the entire execution window even while cases were
    actively being scored.
    """
    from fred_evaluation_backend.workers._activity_context import get_store

    store = get_store()
    await store.update_run_state(run_id, "running")
    await store.create_run_event(run_id, kind="run_started", payload_json=None)


@activity.defn(name="fetch_run_cases")
async def fetch_run_cases(run_id: str) -> list[str]:
    from fred_evaluation_backend.workers._activity_context import get_store

    cases = await get_store().list_cases_by_run(run_id, limit=10000)
    return [c.case_id for c in cases]


@activity.defn(name="run_case_for_run")
async def run_case_for_run(payload: RunCaseInput) -> None:
    """Execute and score one case of a Run — config read from the Run row.

    Every exit path ends with a per-case result written and the Run's
    aggregate progress refreshed:
    - agent-call and scoring failures are already handled inside
      `execute_and_score_case` (it writes the case as `error` and returns);
    - a failure in the setup done *here* — resolving the run/case rows or
      preparing the managed-instance execution (e.g. an auth error from the
      Control Plane) — used to propagate as an unhandled activity exception.
      Once retries were exhausted that took the whole workflow down before
      `finalize_run` ever ran, leaving the Run stuck `pending` in the DB
      forever even though Temporal itself reached a terminal state for the
      workflow. It's now caught here and converted into the same per-case
      `error` outcome as any other case failure.
    """
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
    from fred_evaluation_backend.workers.activities import (
        emit_run_event,
        execute_and_score_case,
    )

    store = get_store()
    config = get_config()
    cp_client = get_cp_client()
    agent_client = get_agent_client()

    try:
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
    except Exception as exc:
        logger.error(
            "[RUN-CASE] run=%s case=%s setup failed before scoring: %s",
            payload.run_id,
            payload.case_id,
            exc,
        )
        await store.update_case_result(
            payload.case_id,
            status="error",
            outcome="execution_error",
            verdict="failed",
            actual_output=None,
            latency_ms=None,
            execution_error=str(exc),
            scoring_errors_json=None,
            structural_checks_json=None,
        )
        await emit_run_event(payload.run_id, payload.case_id, "case_error", store)

    # Refresh the Run's aggregate progress now that this case has a final
    # result. This is what makes the runs-list progress increment as cases
    # finish instead of jumping straight from 0/N to N/N once the whole run
    # (including every other case's scoring) is done.
    refreshed = await store.list_cases_by_run(payload.run_id, limit=10000)
    agg = summarize_cases(refreshed)
    await store.update_run_aggregates(
        payload.run_id,
        completed_cases=agg.completed,
        passed_cases=agg.passed,
        failed_cases=agg.failed,
        execution_error_cases=agg.execution_errors,
        scoring_error_cases=agg.scoring_errors,
        verdict="pending",
        operational_state="running",
    )


@activity.defn(name="finalize_run")
async def finalize_run(run_id: str) -> None:
    """Compute final aggregates for a Run and mark it `completed`.

    `operational_state="completed"` here means "the run finished executing"
    — it is set even when cases failed; the business outcome lives in
    `verdict` (`passed` / `failed` / `inconclusive`). A run that could not
    execute at all is instead left `failed` by `mark_run_failed`, never
    routed through here.
    """

    from fred_evaluation_backend.workers._activity_context import get_store

    store = get_store()
    refreshed = await store.list_cases_by_run(run_id, limit=10000)
    agg = summarize_cases(refreshed)

    run = await store.get_run(run_id)
    insufficient = len([c for c in refreshed if c.verdict == "insufficient"])
    if agg.failed > 0:
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
        completed_cases=agg.completed,
        passed_cases=agg.passed,
        failed_cases=agg.failed,
        execution_error_cases=agg.execution_errors,
        scoring_error_cases=agg.scoring_errors,
        verdict=verdict,
        operational_state="completed",
        metric_averages_json=json.dumps(metric_averages) if metric_averages else None,
    )
    await store.create_run_event(run_id, kind="run_completed", payload_json=None)


@activity.defn(name="mark_run_failed")
async def mark_run_failed(run_id: str) -> None:
    """Force a Run into its terminal `failed` state from whatever partial
    progress it reached.

    Why this exists: if the workflow raises before `finalize_run` can run —
    `fetch_run_cases` exhausting its retries, or `finalize_run` itself
    failing — nothing else ever writes a terminal state for this Run. It
    would stay `pending`/`running` in the DB forever even though Temporal
    marks the workflow execution itself as failed. The runs-list UI treats
    any non-terminal `operational_state` as "still going", so this is the
    only thing that makes a total workflow failure visible.
    """
    from fred_evaluation_backend.workers._activity_context import get_store

    store = get_store()
    refreshed = await store.list_cases_by_run(run_id, limit=10000)
    agg = summarize_cases(refreshed)
    await store.update_run_aggregates(
        run_id,
        completed_cases=agg.completed,
        passed_cases=agg.passed,
        failed_cases=agg.failed,
        execution_error_cases=agg.execution_errors,
        scoring_error_cases=agg.scoring_errors,
        verdict="failed",
        operational_state="failed",
    )
    await store.create_run_event(run_id, kind="run_failed", payload_json=None)


@workflow.defn
class RunWorkflow:
    """Orchestrate one Run: fetch its cases, score them in parallel, finalize.

    Workflow ID = `run-eval-{run_id}` — one durable execution per Run.
    """

    @workflow.run
    async def run(self, payload: RunInput) -> None:
        run_id = payload.run_id
        workflow.logger.info("[RUN-WORKFLOW] starting run=%s", run_id)

        try:
            await workflow.execute_activity(
                mark_run_started,
                run_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            case_ids: list[str] = await workflow.execute_activity(
                fetch_run_cases,
                run_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            results = await asyncio.gather(
                *[
                    workflow.execute_activity(
                        run_case_for_run,
                        RunCaseInput(case_id=case_id, run_id=run_id),
                        start_to_close_timeout=timedelta(hours=2),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    for case_id in case_ids
                ],
                return_exceptions=True,
            )
            for case_id, result in zip(case_ids, results):
                if isinstance(result, BaseException):
                    # run_case_for_run already converts its own setup/scoring
                    # failures into a per-case "error" result — reaching here
                    # means the activity couldn't complete even after retries
                    # (e.g. a worker crash mid-case). Logged so it stays
                    # visible; finalize_run below still runs, and this case
                    # simply won't count as completed.
                    workflow.logger.error(
                        "[RUN-WORKFLOW] run=%s case=%s activity failed: %s",
                        run_id,
                        case_id,
                        result,
                    )

            await workflow.execute_activity(
                finalize_run,
                run_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            workflow.logger.exception("[RUN-WORKFLOW] run=%s failed", run_id)
            await workflow.execute_activity(
                mark_run_failed,
                run_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise

        workflow.logger.info("[RUN-WORKFLOW] run=%s done", run_id)
