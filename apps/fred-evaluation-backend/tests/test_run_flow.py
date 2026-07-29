"""EVAL-05 — start_run persists a Run end-to-end at the data layer.

Real schema (SQLite built from the ORM models) and real stores — no full stack,
no Temporal, no agent. This is the integration test that caught the run-created
case carrying no legacy parent id, which the fakes-based tests could not.

It verifies:
- start_run writes a Run row carrying target/profile/judge + a frozen snapshot,
- cases are materialised on run_id with no legacy parent,
- get_run and list_run_cases read them back,
- a second run of the same evaluation is independent.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine

from fred_evaluation_backend.evaluations import models as _ds_models  # noqa: F401
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.outbound_auth import NoAuthentication
from fred_evaluation_backend.runs import models as _run_models  # noqa: F401
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.base import Base
from fred_evaluation_backend.runs.schemas import ManagedInstanceTarget
from fred_evaluation_backend.runs.store import RunStore


class _FakeControlPlane:
    async def prepare_managed_instance_execution(
        self, *, team_id, agent_instance_id, auth
    ):
        return SimpleNamespace(
            agent_instance_id=agent_instance_id,
            evaluate_url="http://agent/evaluate",
        )


async def _make_stores():
    db = os.path.join(tempfile.mkdtemp(), "eval.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return EvaluationStore(engine), RunStore(engine)


async def _seed_evaluation(evaluation_store: EvaluationStore) -> str:
    await evaluation_store.create_evaluation(
        evaluation_id="eval-1",
        name="usage-arxivai",
        version="v1",
        team_id="team-1",
        created_by="alice",
        origin="upload",
        completeness="minimal",
        cases_json=json.dumps(
            [
                {"input": "q1", "expected_output": "a1"},
                {"input": "q2", "expected_output": None},
            ]
        ),
    )
    return "eval-1"


async def _start(evaluation_id, evaluation_store, run_store, *, instance, by="alice"):
    return await service.start_run(
        evaluation_id=evaluation_id,
        team_id="team-1",
        target=ManagedInstanceTarget(
            kind="managed_instance", agent_instance_id=instance
        ),
        created_by=by,
        store=run_store,
        evaluation_store=evaluation_store,
        control_plane_client=_FakeControlPlane(),
        auth=NoAuthentication(),
        profile="auto",
        judge_profile_id="mistral-small",
        max_concurrency=1,
        metrics=["answer_relevancy"],
        custom_metrics=[],
    )


@pytest.mark.asyncio
async def test_start_run_persists_config_snapshot_and_cases_on_run_id():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store)

    result = await _start(evaluation_id, ds_store, run_store, instance="inst-9")

    run_row = await run_store.get_run(result.run_id)
    assert run_row is not None
    assert run_row.evaluation_id == evaluation_id
    assert run_row.target_instance_id == "inst-9"
    assert run_row.judge_profile_id == "mistral-small"
    assert run_row.metrics_json is not None
    assert json.loads(run_row.metrics_json) == ["answer_relevancy"]
    assert run_row.custom_metrics_json is None
    snapshot = json.loads(run_row.snapshot_json)
    assert snapshot["evaluation_name"] == "usage-arxivai"
    assert snapshot["evaluation_version"] == "v1"

    cases = await run_store.list_cases_by_run(result.run_id, limit=100)
    assert len(cases) == 2
    assert all(c.run_id == result.run_id for c in cases)

    # read side
    run_resp = await service.get_run(result.run_id, store=run_store)
    assert run_resp.snapshot.evaluation_name == "usage-arxivai"
    # The launching identity must be echoed back so the UI can show the run's author.
    assert run_resp.created_by == "alice"
    # The read response must echo the metric selection back — a rerun (or any other
    # caller) needs this to reproduce the same run without re-deriving it.
    assert run_resp.metrics == ["answer_relevancy"]
    assert run_resp.custom_metrics == []
    cases_resp = await service.list_run_cases(result.run_id, store=run_store)
    assert cases_resp.total == 2


@pytest.mark.asyncio
async def test_two_runs_of_the_same_evaluation_are_independent():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store)

    first = await _start(evaluation_id, ds_store, run_store, instance="inst-9")
    second = await _start(
        evaluation_id, ds_store, run_store, instance="inst-42", by="bob"
    )

    assert first.run_id != second.run_id
    listed = await service.list_runs(evaluation_id, store=run_store)
    # The list endpoint is paginated: a runs page plus the full count for the UI.
    # (Both runs are created within the same second, so created_at is a tie and the
    # newest-first order between these two is not asserted — only membership is.)
    assert listed.total == 2
    assert {r.run_id for r in listed.runs} == {first.run_id, second.run_id}


@pytest.mark.asyncio
async def test_run_operations_case_detail_cancel_delete():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store)
    result = await _start(evaluation_id, ds_store, run_store, instance="inst-9")

    # case detail resolves a single case of the run
    cases = await service.list_run_cases(result.run_id, store=run_store)
    one = cases.cases[0]
    detail = await service.get_run_case(result.run_id, one.case_id, store=run_store)
    assert detail.case_id == one.case_id
    with pytest.raises(HTTPException) as exc:
        await service.get_run_case(result.run_id, "nope", store=run_store)
    assert exc.value.status_code == 404

    # cancel moves the run to a terminal state; a second cancel is a 409
    await service.cancel_run(result.run_id, store=run_store)
    assert (await run_store.get_run(result.run_id)).operational_state == "cancelled"
    with pytest.raises(HTTPException) as exc:
        await service.cancel_run(result.run_id, store=run_store)
    assert exc.value.status_code == 409

    # delete removes the run and its cases
    await service.delete_run(result.run_id, store=run_store)
    assert await run_store.get_run(result.run_id) is None
    assert await run_store.list_cases_by_run(result.run_id, limit=100) == []


@pytest.mark.asyncio
async def test_run_aggregates_persist_metric_averages_and_analysis():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store)
    result = await _start(evaluation_id, ds_store, run_store, instance="inst-9")

    await run_store.update_run_aggregates(
        result.run_id,
        completed_cases=2,
        passed_cases=2,
        failed_cases=0,
        insufficient_cases=0,
        execution_error_cases=0,
        scoring_error_cases=0,
        verdict="passed",
        operational_state="completed",
        metric_averages_json=json.dumps({"faithfulness": 0.9}),
    )
    await run_store.update_run_analysis(
        result.run_id, analysis_json=json.dumps({"analysis": {"summary": "ok"}})
    )

    row = await run_store.get_run(result.run_id)
    assert json.loads(row.metric_averages_json) == {"faithfulness": 0.9}
    assert json.loads(row.analysis_json)["analysis"]["summary"] == "ok"


@pytest.mark.asyncio
async def test_run_store_task_lookup_and_scopes():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store)

    first = await _start(evaluation_id, ds_store, run_store, instance="inst-9")
    second = await _start(
        evaluation_id, ds_store, run_store, instance="inst-42", by="bob"
    )

    assert (await run_store.get_run_by_task_id(first.task_id)).run_id == first.run_id
    assert [r.run_id for r in await run_store.list_runs_by_creator("alice")] == [
        first.run_id
    ]
    assert {r.run_id for r in await run_store.list_runs_by_team("team-1")} == {
        first.run_id,
        second.run_id,
    }
