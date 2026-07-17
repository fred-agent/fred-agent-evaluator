"""EVAL-05 — start_run persists a Run end-to-end at the data layer.

Real schema (SQLite built from the ORM models) and real stores — no full stack,
no Temporal, no agent. This is the integration test that caught the run-created
case having a null campaign_id the fakes-based tests could not.

It verifies:
- start_run writes a Run row carrying target/profile/judge + a frozen snapshot,
- cases are materialised on run_id with no campaign,
- get_run and list_run_cases read them back,
- a second run of the same evaluation is independent.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from fred_evaluation_backend.campaigns import models as _run_models  # noqa: F401
from fred_evaluation_backend.campaigns import service
from fred_evaluation_backend.campaigns.base import Base
from fred_evaluation_backend.campaigns.schemas import ManagedInstanceTarget
from fred_evaluation_backend.campaigns.store import EvaluationStore
from fred_evaluation_backend.datasets import models as _ds_models  # noqa: F401
from fred_evaluation_backend.datasets.store import DatasetStore
from fred_evaluation_backend.execution.outbound_auth import NoAuthentication


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
    return DatasetStore(engine), EvaluationStore(engine)


async def _seed_evaluation(ds_store: DatasetStore) -> str:
    await ds_store.create_dataset(
        dataset_id="eval-ds-1",
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
    return "eval-ds-1"


async def _start(evaluation_id, ds_store, run_store, *, instance, by="alice"):
    return await service.start_run(
        evaluation_id=evaluation_id,
        team_id="team-1",
        target=ManagedInstanceTarget(
            kind="managed_instance", agent_instance_id=instance
        ),
        created_by=by,
        store=run_store,
        dataset_store=ds_store,
        control_plane_client=_FakeControlPlane(),
        auth=NoAuthentication(),
        profile="auto",
        judge_profile_id="mistral-small",
    )


@pytest.mark.asyncio
async def test_start_run_persists_config_snapshot_and_cases_on_run_id():
    ds_store, run_store = await _make_stores()
    evaluation_id = await _seed_evaluation(ds_store)

    result = await _start(evaluation_id, ds_store, run_store, instance="inst-9")

    run_row = await run_store.get_run(result.run_id)
    assert run_row.evaluation_id == evaluation_id
    assert run_row.target_instance_id == "inst-9"
    assert run_row.judge_profile_id == "mistral-small"
    assert run_row.campaign_id is None  # a Run has no campaign

    snapshot = json.loads(run_row.snapshot_json)
    assert snapshot["evaluation_name"] == "usage-arxivai"
    assert snapshot["evaluation_version"] == "v1"

    cases = await run_store.list_cases_by_run(result.run_id, limit=100)
    assert len(cases) == 2
    assert all(c.campaign_id is None and c.run_id == result.run_id for c in cases)

    # read side
    run_resp = await service.get_run(result.run_id, store=run_store)
    assert run_resp.snapshot.evaluation_name == "usage-arxivai"
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
    runs = await service.list_runs(evaluation_id, store=run_store)
    assert len(runs) == 2
