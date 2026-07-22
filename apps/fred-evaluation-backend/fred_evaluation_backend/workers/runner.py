from __future__ import annotations

import asyncio
import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.config.models import EvaluationConfig
from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.outbound_auth import ServiceAuthentication
from fred_evaluation_backend.model.factory import build_judge_model
from fred_evaluation_backend.runs.schemas import RunSnapshot
from fred_evaluation_backend.runs.store import RunStore
from fred_evaluation_backend.workers.activities import execute_and_score_case

logger = logging.getLogger(__name__)


class RunRunner:
    def __init__(
        self,
        *,
        config: EvaluationConfig,
        engine: AsyncEngine,
        cp_client: ControlPlaneClient,
    ) -> None:
        self._config = config
        self._store = RunStore(engine)
        self._cp_client = cp_client
        self._agent_client = AgentClient()
        self._running: set[str] = set()

    async def run_forever(self) -> None:
        logger.info(
            "[RUNNER] starting — default_max_concurrency=%d poll_interval=%ds "
            "(each run is paced by its own frozen snapshot)",
            self._config.worker.max_concurrent_cases,
            self._config.worker.poll_interval_seconds,
        )
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("[RUNNER] unhandled error in tick")
            await asyncio.sleep(self._config.worker.poll_interval_seconds)

    async def _tick(self) -> None:
        rows = await self._store.list_runs_by_state("pending", limit=10)
        for run in rows:
            if run.run_id not in self._running:
                self._running.add(run.run_id)
                asyncio.create_task(
                    self._run_run(run),
                    name=f"run-{run.run_id}",
                )

    async def _run_run(self, run) -> None:
        run_id = run.run_id
        logger.info("[RUNNER] starting run=%s", run_id)
        try:
            await self._store.update_run_state(run_id, "running")
            await self._store.create_run_event(
                run_id, kind="run_started", payload_json=None
            )
            await self._execute_run(run)
        except Exception:
            logger.exception("[RUNNER] run=%s failed unexpectedly", run_id)
            await self._store.update_run_aggregates(
                run_id,
                completed_cases=0,
                passed_cases=0,
                failed_cases=0,
                insufficient_cases=0,
                execution_error_cases=0,
                scoring_error_cases=0,
                verdict="failed",
                operational_state="error",
            )
        finally:
            self._running.discard(run_id)

    async def _execute_run(self, run) -> None:
        from fred_deepeval_cli.core.models import CustomMetricSpec

        run_id = run.run_id
        # Read from the run's own frozen snapshot, exactly like the Temporal path reads
        # it from the workflow payload — so both engines pace a given run identically,
        # and a config change never re-paces a run that is already under way.
        snapshot = RunSnapshot.model_validate_json(run.snapshot_json)
        max_concurrency = max(1, (snapshot.execution or {}).get("max_concurrency", 1))
        limiter = asyncio.Semaphore(max_concurrency)

        try:
            prep = await self._cp_client.prepare_managed_instance_execution(
                team_id=run.team_id,
                agent_instance_id=run.target_instance_id,
                auth=ServiceAuthentication(),
            )
            evaluate_url = prep.evaluate_url
        except Exception as exc:
            logger.error("[RUNNER] run=%s cannot prepare execution: %s", run_id, exc)
            await self._store.update_run_aggregates(
                run_id,
                completed_cases=0,
                passed_cases=0,
                failed_cases=0,
                insufficient_cases=0,
                execution_error_cases=run.total_cases,
                scoring_error_cases=0,
                verdict="failed",
                operational_state="error",
            )
            return

        judge_profile = self._config.worker.judge_profiles.get(run.judge_profile_id)
        judge = None
        if judge_profile is not None:
            try:
                judge = build_judge_model(judge_profile)
            except Exception as exc:
                logger.warning(
                    "[RUNNER] run=%s cannot build judge '%s': %s — proceeding without scoring",
                    run_id,
                    run.judge_profile_id,
                    exc,
                )

        custom_metrics = [
            CustomMetricSpec.model_validate(m)
            for m in json.loads(run.custom_metrics_json or "[]")
        ]
        metrics: list[str] = json.loads(run.metrics_json or "[]")
        cases = await self._store.list_cases_by_run(run_id, limit=10000)

        async def _run_case(case) -> None:
            async with limiter:
                try:
                    await execute_and_score_case(
                        case_id=case.case_id,
                        run_id=run_id,
                        created_by=run.created_by,
                        input=case.input,
                        expected_output=case.expected_output,
                        agent_id=run.target_agent_id,
                        agent_instance_id=prep.agent_instance_id,
                        session_id=str(uuid.uuid4()),
                        evaluate_url=evaluate_url,
                        team_id=run.team_id,
                        token_provider=self._cp_client.m2m_token_provider,
                        profile=run.profile,
                        judge=judge,
                        custom_metrics=custom_metrics,
                        metrics=metrics,
                        store=self._store,
                        agent_client=self._agent_client,
                    )
                except Exception as exc:
                    logger.error(
                        "[RUNNER] case=%s unhandled exception: %s", case.case_id, exc
                    )
                    await self._store.update_case_result(
                        case.case_id,
                        status="error",
                        outcome="execution_error",
                        verdict="failed",
                        actual_output=None,
                        latency_ms=None,
                        execution_error=str(exc),
                        scoring_errors_json=None,
                        structural_checks_json=None,
                    )

        results = await asyncio.gather(
            *[_run_case(c) for c in cases], return_exceptions=True
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "[RUNNER] run=%s case[%d] unhandled exception: %s",
                    run_id,
                    i,
                    result,
                )

        refreshed = await self._store.list_cases_by_run(run_id, limit=10000)
        completed = len([c for c in refreshed if c.status in ("completed", "error")])
        passed = len([c for c in refreshed if c.verdict == "passed"])
        failed = len([c for c in refreshed if c.verdict == "failed"])
        insufficient = len([c for c in refreshed if c.verdict == "insufficient"])
        exec_errors = len([c for c in refreshed if c.outcome == "execution_error"])
        scoring_errors = len(
            [c for c in refreshed if c.scoring_errors_json is not None]
        )

        if failed > 0:
            run_verdict = "failed"
        elif insufficient >= (run.total_cases or 1) / 2:
            run_verdict = "inconclusive"
        else:
            run_verdict = "passed"

        all_metrics = await self._store.list_metrics_by_run(run_id)
        metric_scores: dict[str, list[float]] = {}
        for m in all_metrics:
            if m.score is not None:
                try:
                    score_val = float(m.score)
                    metric_scores.setdefault(m.name, []).append(score_val)
                except ValueError:
                    pass
        metric_averages = {
            name: sum(scores) / len(scores) for name, scores in metric_scores.items()
        }
        metric_averages_json = json.dumps(metric_averages) if metric_averages else None

        await self._store.update_run_aggregates(
            run_id,
            completed_cases=completed,
            passed_cases=passed,
            failed_cases=failed,
            insufficient_cases=insufficient,
            execution_error_cases=exec_errors,
            scoring_error_cases=scoring_errors,
            verdict=run_verdict,
            operational_state="completed",
            metric_averages_json=metric_averages_json,
        )
        await self._store.create_run_event(
            run_id, kind="run_completed", payload_json=None
        )
        logger.info(
            "[RUNNER] run=%s completed passed=%d failed=%d",
            run_id,
            passed,
            failed,
        )
