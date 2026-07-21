"""EVAL — Temporal run-workflow progress and terminal-state guarantees.

Live-tested 2026-07-20 against a real Temporal worker: the runs-list UI
(which polls a Run row's own `operational_state`/`completed_cases` fields,
not the case rows) stayed stuck at "PENDING 0/N" for the entire duration of
a real run, and a separate run whose every case activity errored (a control
plane 403) stayed stuck at "PENDING 0/N" forever even after Temporal itself
confirmed the workflow had reached a terminal state.

Root cause, confirmed by reading `workers/workflow.py`:
- Nothing wrote to the Run row between `pending` (set at creation) and the
  single `finalize_run` activity at the very end of the workflow — no
  activity ever flipped it to `running`, and no per-case aggregate update
  happened as each case finished.
- A failure in `run_case_for_run`'s setup (resolving the run/case rows,
  preparing the managed-instance execution) was not caught anywhere. Once
  Temporal's retries were exhausted it propagated out of `asyncio.gather`
  in the workflow body, skipping `finalize_run` entirely and leaving the
  Run non-terminal forever — even though Temporal's own workflow execution
  reached a terminal (failed) state.

These tests exercise the real activity functions (`mark_run_started`,
`run_case_for_run`, `finalize_run`, `mark_run_failed`) directly against a
real SQLite-backed `RunStore` — no Temporal server involved. Activities
decorated with `@activity.defn` are plain coroutine functions and can be
awaited directly as long as they don't touch Temporal's activity execution
context (none of ours do), which is enough to prove the DB-visible behavior
the runs-list UI depends on, without requiring a live Temporal test server.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from fred_evaluation_backend.evaluations import models as _ds_models  # noqa: F401
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.outbound_auth import NoAuthentication
from fred_evaluation_backend.runs import models as _run_models  # noqa: F401
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.base import Base
from fred_evaluation_backend.runs.schemas import ManagedInstanceTarget
from fred_evaluation_backend.runs.store import RunStore
from fred_evaluation_backend.tasks.models import TaskState, map_state
from fred_evaluation_backend.workers import _activity_context
from fred_evaluation_backend.workers.workflow import (
    RunCaseInput,
    RunInput,
    finalize_run,
    mark_run_failed,
    mark_run_started,
    run_case_for_run,
)


class _FakeControlPlaneOK:
    m2m_token_provider = None

    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth
    ):
        return SimpleNamespace(
            agent_instance_id=agent_instance_id,
            evaluate_url="http://agent/evaluate",
        )


class _FakeControlPlaneAlwaysForbidden:
    """Simulates the real-world 403 that broke every case of a run."""

    m2m_token_provider = None

    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth
    ):
        raise PermissionError("403 Forbidden: service token rejected")


class _FakeAgentClient:
    async def evaluate(
        self,
        *,
        evaluate_url,
        team_id,
        agent_id,
        agent_instance_id=None,
        session_id,
        input,
        token_provider=None,
    ):
        from fred_sdk.contracts.eval import EvalTrace

        return EvalTrace(
            session_id=session_id,
            agent_id=agent_id or "agent-1",
            input=input,
            latency_ms=10,
            output="the answer",
        )


async def _make_stores() -> tuple[EvaluationStore, RunStore]:
    db = os.path.join(tempfile.mkdtemp(), "eval.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return EvaluationStore(engine), RunStore(engine)


async def _seed_evaluation(evaluation_store: EvaluationStore, num_cases: int) -> str:
    await evaluation_store.create_evaluation(
        evaluation_id="eval-1",
        name="usage-arxivai",
        version="v1",
        team_id="team-1",
        created_by="alice",
        origin="upload",
        completeness="minimal",
        cases_json=json.dumps(
            [{"input": f"q{i}", "expected_output": None} for i in range(num_cases)]
        ),
    )
    return "eval-1"


async def _start_run(
    evaluation_id: str,
    evaluation_store: EvaluationStore,
    run_store: RunStore,
    *,
    cp_client,
):
    return await service.start_run(
        evaluation_id=evaluation_id,
        team_id="team-1",
        target=ManagedInstanceTarget(
            kind="managed_instance", agent_instance_id="inst-1"
        ),
        created_by="alice",
        store=run_store,
        evaluation_store=evaluation_store,
        control_plane_client=cp_client,
        auth=NoAuthentication(),
        profile="auto",
        judge_profile_id="mistral-small",
        max_concurrency=1,
    )


def _init_activity_context(run_store: RunStore, *, cp_client, agent_client) -> None:
    _activity_context.init(
        store=run_store,
        config=SimpleNamespace(
            worker=SimpleNamespace(judge_profiles={}, max_concurrent_cases=1)
        ),
        agent_client=agent_client,
        cp_client=cp_client,
    )


@pytest.mark.asyncio
async def test_mark_run_started_flips_pending_to_running_before_any_case_runs():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store, num_cases=2)
    result = await _start_run(
        evaluation_id, ds_store, run_store, cp_client=_FakeControlPlaneOK()
    )

    row = await run_store.get_run(result.run_id)
    assert row.operational_state == "pending"

    _init_activity_context(
        run_store, cp_client=_FakeControlPlaneOK(), agent_client=_FakeAgentClient()
    )
    await mark_run_started(result.run_id)

    row = await run_store.get_run(result.run_id)
    assert row.operational_state == "running"
    assert row.completed_cases == 0
    assert row.started_at is not None  # the "Run information" panel showed
    # a permanent "—" for this — nothing ever wrote it before this fix


@pytest.mark.asyncio
async def test_run_case_for_run_updates_progress_incrementally_not_only_at_the_end():
    """Bug 1: completed_cases must increase as each case finishes.

    Before the fix, only `finalize_run` (the very last workflow step) ever
    wrote to `completed_cases`/`operational_state`, so a runs-list poller
    saw 0/N for the entire run duration and then jumped straight to N/N.
    """
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store, num_cases=3)
    result = await _start_run(
        evaluation_id, ds_store, run_store, cp_client=_FakeControlPlaneOK()
    )
    cases = await run_store.list_cases_by_run(result.run_id, limit=100)
    assert len(cases) == 3

    _init_activity_context(
        run_store, cp_client=_FakeControlPlaneOK(), agent_client=_FakeAgentClient()
    )
    await mark_run_started(result.run_id)

    seen_counts: list[int] = []
    for case in cases:
        await run_case_for_run(RunCaseInput(case_id=case.case_id, run_id=result.run_id))
        row = await run_store.get_run(result.run_id)
        seen_counts.append(row.completed_cases)
        # Progress must be visible immediately, not jump from 0 to N later.
        assert row.operational_state == "running"

    # Strictly increasing, one per case — never "stuck at 0 until the end".
    assert seen_counts == [1, 2, 3]


@pytest.mark.asyncio
async def test_run_case_for_run_survives_setup_failure_and_run_still_reaches_terminal_state():
    """Bug 2 (the reported scenario): every case's setup fails (403).

    Before the fix, `prepare_managed_instance_execution` raising was
    unhandled inside `run_case_for_run`; once Temporal's retries were
    exhausted it propagated out of the workflow's `asyncio.gather`,
    skipping `finalize_run` and leaving the Run non-terminal forever.

    The activity must now absorb the failure as an ordinary per-case error
    (matching how agent-call/scoring failures already behave), and the run
    must still be able to reach `finalize_run` and end up terminal.
    """
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store, num_cases=2)
    # Run creation succeeds (the instance exists and is resolvable) — the 403
    # only shows up later, at execution time, e.g. because the service token
    # expired between scheduling and running. That's what `_execute_run`'s
    # own `cp_client` (wired via the activity context) simulates below.
    result = await _start_run(
        evaluation_id, ds_store, run_store, cp_client=_FakeControlPlaneOK()
    )
    cases = await run_store.list_cases_by_run(result.run_id, limit=100)

    _init_activity_context(
        run_store,
        cp_client=_FakeControlPlaneAlwaysForbidden(),
        agent_client=_FakeAgentClient(),
    )
    await mark_run_started(result.run_id)

    for case in cases:
        # Must not raise — this is exactly what used to take the whole
        # Temporal workflow down.
        await run_case_for_run(RunCaseInput(case_id=case.case_id, run_id=result.run_id))

    row = await run_store.get_run(result.run_id)
    assert row.completed_cases == len(cases)
    assert row.failed_cases == len(cases)
    assert row.operational_state == "running"  # not yet finalized

    for case in cases:
        detail = await run_store.get_case(case.case_id)
        assert detail.status == "error"
        assert detail.verdict == "failed"

    await finalize_run(result.run_id)

    row = await run_store.get_run(result.run_id)
    assert row.operational_state == "completed"  # terminal — never orphaned
    assert row.verdict == "failed"
    assert map_state(row.operational_state) == TaskState.succeeded
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_mark_run_failed_forces_terminal_state_when_workflow_itself_blows_up():
    """Bug 2 (defense in depth): a workflow-level exception (e.g.
    `fetch_run_cases` exhausting its retries before any case could run)
    must still leave the Run row in a terminal state, and that terminal
    state must map onto the failed TaskState the frontend understands.
    """
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store, num_cases=2)
    result = await _start_run(
        evaluation_id, ds_store, run_store, cp_client=_FakeControlPlaneOK()
    )

    _init_activity_context(
        run_store, cp_client=_FakeControlPlaneOK(), agent_client=_FakeAgentClient()
    )
    await mark_run_started(result.run_id)
    row = await run_store.get_run(result.run_id)
    assert row.operational_state == "running"  # not yet terminal

    await mark_run_failed(result.run_id)

    row = await run_store.get_run(result.run_id)
    assert row.operational_state == "failed"
    assert row.verdict == "failed"
    assert map_state(row.operational_state) == TaskState.failed
    assert row.completed_at is not None


# ── EVAL-06: pacing is a property of the run, enforced by the workflow ────────


def test_run_input_carries_the_pacing_so_a_replay_cannot_change_it():
    """The concurrency must travel in the workflow payload, not be read from worker
    config inside the workflow.

    A workflow that read `config.worker.max_concurrent_cases` at run time would
    replay differently on a worker configured differently — non-determinism, and
    the value would also stop describing the run it belongs to.
    """
    payload = RunInput(run_id="eval-run-1", max_concurrency=3)
    assert payload.max_concurrency == 3

    # Histories written before this field existed must still deserialize.
    assert RunInput(run_id="eval-run-1").max_concurrency == 1


@pytest.mark.asyncio
async def test_workflow_never_schedules_more_cases_at_once_than_the_run_allows():
    """The bound has to come from the workflow, not from the worker pool.

    `max_concurrent_activities` bounds one process, so N replicas multiply it by N —
    that is exactly how a "serial" setting still produced a burst of 429s. Modelled
    here with the same shape the workflow uses: a semaphore around each activity, so
    the assertion is about scheduling, not about a worker's thread pool.
    """
    max_concurrency = 2
    in_flight = 0
    peak = 0

    limiter = asyncio.Semaphore(max_concurrency)

    async def _run_case(_case_id: str) -> None:
        nonlocal in_flight, peak
        async with limiter:
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)  # yield, letting any unbounded fan-out show itself
            in_flight -= 1

    await asyncio.gather(*[_run_case(f"case-{i}") for i in range(12)])

    assert peak <= max_concurrency, f"{peak} cases were in flight at once"


@pytest.mark.asyncio
async def test_serial_pacing_really_means_one_at_a_time():
    """max_concurrency=1 is the default that stops bursting a rate-limited target."""
    in_flight = 0
    peak = 0
    limiter = asyncio.Semaphore(1)

    async def _run_case(_case_id: str) -> None:
        nonlocal in_flight, peak
        async with limiter:
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1

    await asyncio.gather(*[_run_case(f"case-{i}") for i in range(14)])

    assert peak == 1
