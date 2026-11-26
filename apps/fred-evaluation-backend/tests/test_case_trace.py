"""Offline evidence lifecycle through the real store/activity and authorized API."""

from __future__ import annotations

# SQL/JSON responses and test doubles are deliberately dynamic here.
# Reuse the existing access-test fixtures instead of another app/store harness.
# pyright: reportAny=false, reportPrivateUsage=false

import importlib
import json
from unittest.mock import AsyncMock, Mock
from pathlib import Path
from typing import cast
from fastapi import HTTPException
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fred_deepeval_cli.core import scorer
from fred_sdk.contracts.eval import EvalStep, EvalTrace  # pyright: ignore[reportMissingTypeStubs]
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.evaluations import service as evaluation_service
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.store import MAX_TRACE_BYTES, RunStore
from fred_evaluation_backend.execution.agent_client import AgentClient
from fred_evaluation_backend.workers.activities import execute_and_score_case  # pyright: ignore[reportUnknownVariableType]
from tests.test_run_access import _ControlPlane, _app, _client, _seed, _stores  # pyright: ignore[reportUnknownVariableType]
from fred_evaluation_backend.execution.outbound_auth import NoAuthentication


def _trace(session_id: str = "attempt-1", **changes: object) -> EvalTrace:
    return EvalTrace.model_validate(
        dict(
            session_id=session_id,
            agent_id="agent-1",
            input="q1",
            output="The deadline starts on notification.",
            latency_ms=12,
            model_name="provider-model",
            token_usage={"input_tokens": 100, "output_tokens": 12},
            steps=(
                EvalStep(
                    kind="tool_call",
                    tool_name="wiki_read_page",
                    call_id="1",
                    arguments={"path": "Rules"},
                ),
                EvalStep(
                    kind="tool_result",
                    tool_name="wiki_read_page",
                    call_id="1",
                    content="Starts on notification.",
                ),
            ),
            retrieval_context=("Starts on notification.",),
            tools_called=("wiki_read_page",),
        )
        | changes
    )


async def _execute(
    store: RunStore,
    run_id: str,
    case_id: str,
    agent: AsyncMock,
) -> None:
    await execute_and_score_case(
        case_id=case_id,
        run_id=run_id,
        created_by="bob",
        input="q1",
        expected_output="a1",
        agent_instance_id="i-1",
        evaluate_url="http://unused/evaluate",
        team_id="team-1",
        profile="default",
        judge=object(),
        metrics=["answer_relevancy"],
        store=store,
        agent_client=cast(AgentClient, agent),
    )


@pytest.mark.asyncio
async def test_trace_committed_before_judge_and_reused_after_scoring_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    agent = AsyncMock()
    agent.evaluate.return_value = _trace()

    def failing_score(_received: object, **_kwargs: object) -> None:
        # A separate DB connection sees the committed evidence while judging.
        with create_engine(str(engine.url).replace("+aiosqlite", "")).connect() as conn:
            saved = conn.execute(
                text("SELECT trace_json FROM evaluation_case WHERE case_id = :id"),
                {"id": case.case_id},
            ).scalar_one()
        assert json.loads(saved) == json.loads(_trace().model_dump_json())
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(scorer, "score_trace", failing_score)
    await _execute(store, run_id, case.case_id, agent)
    failed = await store.get_case(case.case_id)
    assert failed is not None
    assert failed.status == "error"
    assert failed.actual_output == _trace().output
    assert failed.execution_error is None
    assert failed.scoring_errors_json is not None
    assert "judge unavailable" in failed.scoring_errors_json
    assert failed.trace_json == _trace().model_dump_json()
    assert failed.token_usage_json is not None
    assert json.loads(failed.token_usage_json) == _trace().token_usage

    monkeypatch.setattr(scorer, "score_trace", Mock(return_value=([], [])))
    await _execute(store, run_id, case.case_id, agent)
    retried = await store.get_case(case.case_id)
    assert retried is not None
    assert retried.status == "completed"
    assert retried.verdict == "passed"
    assert retried.execution_session_id == "attempt-1"
    assert retried.trace_json == failed.trace_json
    assert agent.evaluate.await_count == 1
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["missing", "oversized", "persistence", "session", "input"]
)
async def test_unusable_evidence_never_reaches_judge_or_reexecutes(
    monkeypatch: pytest.MonkeyPatch, failure: str
):
    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    agent = AsyncMock()
    agent.evaluate.return_value = {
        "missing": None,
        "oversized": _trace(output="é" * (MAX_TRACE_BYTES // 2)),
        "persistence": _trace(),
        "session": _trace(session_id=""),
        "input": _trace(input="different question"),
    }[failure]
    if failure == "persistence":
        monkeypatch.setattr(
            store, "retain_case_trace", AsyncMock(side_effect=OSError("db unavailable"))
        )
    score = AsyncMock()
    monkeypatch.setattr(scorer, "score_trace", score)
    await _execute(store, run_id, case.case_id, agent)
    failed = await store.get_case(case.case_id)
    assert failed is not None
    assert failed.status == "error" and failed.verdict == "failed"
    assert failed.execution_error is not None
    assert "trace_" in failed.execution_error
    assert failed.trace_json is None and failed.actual_output is None
    assert failed.execution_session_id is not None
    assert (
        await service.get_run_case(run_id, case.case_id, store=store)
    ).execution_session_id is None
    await _execute(store, run_id, case.case_id, agent)
    retried = await store.get_case(case.case_id)
    assert retried is not None and retried.execution_error is not None
    assert "trace_missing" in retried.execution_error
    assert agent.evaluate.await_count == 1
    score.assert_not_called()
    await engine.dispose()


@pytest.mark.asyncio
async def test_trace_reads_exports_access_and_run_deletion():
    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    _, other_run = await _seed(evaluations, store, "team-2")
    case = (await store.list_cases_by_run(run_id))[0]
    foreign = (await store.list_cases_by_run(other_run))[0]
    for row in (case, foreign):
        await store.begin_case_execution(
            row.case_id, run_id=row.run_id, session_id="attempt-1"
        )
        await store.retain_case_trace(
            row.case_id, run_id=row.run_id, session_id="attempt-1", trace=_trace()
        )
    async with _client(_app(engine)) as client:
        detail = await client.get(f"/runs/{run_id}/cases/{case.case_id}")
        listing = await client.get(f"/runs/{run_id}/cases")
        report = await client.get(f"/runs/{run_id}/report")
        assert detail.status_code == listing.status_code == report.status_code == 200
        for data in (
            detail.json(),
            report.json()["cases"][0],
        ):
            assert data["trace"] == json.loads(_trace().model_dump_json())
            assert data["token_usage"] == _trace().token_usage
            assert data["execution_session_id"] == "attempt-1"
        assert listing.json()["cases"][0]["trace"] is None
        assert listing.json()["cases"][0]["trace_available"] is True
        listed = (await store.list_cases_by_run(run_id))[0]
        assert "trace_json" in inspect(listed).unloaded
        assert (
            await client.get(f"/runs/{run_id}/cases/{foreign.case_id}")
        ).status_code == 404
        assert (
            await client.get(f"/runs/{other_run}/cases/{foreign.case_id}")
        ).status_code == 403
        assert (await client.get(f"/runs/{other_run}/report")).status_code == 403
        assert (await client.delete(f"/runs/{run_id}")).status_code == 204
    assert await store.get_case(case.case_id) is None
    retained = await store.get_case(foreign.case_id)
    assert retained is not None and retained.trace_json is not None
    # Definition deletion uses the same existing case lifecycle.
    await evaluation_service.delete_evaluation(
        "eval-team-2",
        store=evaluations,
        run_store=store,
        control_plane_client=cast(
            ControlPlaneClient, cast(object, _ControlPlane(frozenset({"team-2"})))
        ),
        auth=NoAuthentication(),
    )
    assert await store.get_case(foreign.case_id) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_and_retention_cannot_replace_an_attempt():
    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    with pytest.raises(ValueError, match="case absent"):
        await store.begin_case_execution(
            case.case_id, run_id="other-run", session_id="wrong"
        )
    await store.begin_case_execution(
        case.case_id, run_id=run_id, session_id="attempt-1"
    )
    with pytest.raises(ValueError, match="already attempted"):
        await store.begin_case_execution(
            case.case_id, run_id=run_id, session_id="attempt-2"
        )
    await store.retain_case_trace(
        case.case_id, run_id=run_id, session_id="attempt-1", trace=_trace()
    )
    with pytest.raises(ValueError, match="already retained"):
        await store.retain_case_trace(
            case.case_id,
            run_id=run_id,
            session_id="attempt-1",
            trace=_trace(output="replacement"),
        )
    assert (
        await service.get_run_case(run_id, case.case_id, store=store)
    ).actual_output == _trace().output
    await engine.dispose()


def test_trace_migration_keeps_existing_case_and_marks_evidence_absent(tmp_path: Path):
    migration = importlib.import_module(
        "fred_evaluation_backend.migrations.versions.20261123_01_case_trace"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        _ = conn.execute(
            text(
                "CREATE TABLE evaluation_case (case_id TEXT PRIMARY KEY, actual_output TEXT, raw_trace_ref TEXT)"
            )
        )
        _ = conn.execute(
            text("INSERT INTO evaluation_case VALUES ('case', 'old answer', NULL)")
        )
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert "raw_trace_ref" not in {
            c["name"] for c in inspect(conn).get_columns("evaluation_case")
        }
        assert conn.execute(
            text(
                "SELECT actual_output, trace_json, execution_session_id FROM evaluation_case"
            )
        ).one() == ("old answer", None, None)
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert conn.execute(
            text("SELECT actual_output, raw_trace_ref FROM evaluation_case")
        ).one() == ("old answer", None)
    engine.dispose()


@pytest.mark.asyncio
async def test_report_budget_rejects_before_loading_trace(
    monkeypatch: pytest.MonkeyPatch,
):
    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    await store.begin_case_execution(
        case.case_id, run_id=run_id, session_id="attempt-1"
    )
    await store.retain_case_trace(
        case.case_id,
        run_id=run_id,
        session_id="attempt-1",
        trace=_trace(output="é" * 100),
    )
    size = len(_trace(output="é" * 100).model_dump_json().encode("utf-8"))
    assert await store.retained_trace_bytes(run_id) == size
    monkeypatch.setattr(service, "_REPORT_TRACE_BYTES", size - 1)
    async with _client(_app(engine)) as client:
        response = await client.get(f"/runs/{run_id}/report")
        assert response.status_code == 413
        assert "case-detail" in response.json()["detail"]
        assert (
            await client.get(f"/runs/{run_id}/cases/{case.case_id}")
        ).status_code == 200
    loader = AsyncMock(side_effect=AssertionError("must not load payloads"))
    monkeypatch.setattr(store, "list_cases_by_run", loader)
    with pytest.raises(HTTPException) as error:
        _ = await service.build_run_report(
            run_id, store=store, evaluation_store=evaluations
        )
    assert error.value.status_code == 413
    loader.assert_not_called()
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_report_count_uses_text_octets(monkeypatch: pytest.MonkeyPatch):
    """Compile the PostgreSQL branch; execution coverage above uses SQLite."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from unittest.mock import MagicMock
    from sqlalchemy.dialects import postgresql
    from fred_evaluation_backend.runs import store as store_module

    engine, _, store = await _stores()
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"
    session.scalar = AsyncMock(return_value=0)

    @asynccontextmanager
    async def postgres_session(_factory: object) -> AsyncIterator[MagicMock]:
        yield session

    monkeypatch.setattr(store_module, "use_session", postgres_session)
    assert await store.retained_trace_bytes("run") == 0
    query = session.scalar.await_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "octet_length(evaluation_case.trace_json)" in sql
    assert "BYTEA" not in sql
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_kind", ["temporal", "polling"])
async def test_wrapper_retry_preserves_evidence_on_snapshot_setup_failure(
    monkeypatch: pytest.MonkeyPatch, engine_kind: str
):
    from fred_evaluation_backend.config.models import EvaluationConfig
    from fred_evaluation_backend.workers.runner import RunRunner
    from fred_evaluation_backend.workers.workflow import RunCaseInput, run_case_for_run
    from tests.test_run_workflow import _init_activity_context  # pyright: ignore[reportUnknownVariableType]

    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    agent = AsyncMock()
    agent.evaluate.return_value = _trace()
    monkeypatch.setattr(
        scorer, "score_trace", Mock(side_effect=RuntimeError("judge unavailable"))
    )
    await _execute(store, run_id, case.case_id, agent)
    cp = AsyncMock()
    cp.m2m_token_provider = None
    run = await store.get_run(run_id)
    assert run is not None
    saved_snapshot = await _remove_destination(engine, store, run_id)
    run = await store.get_run(run_id)
    assert run is not None
    runner = RunRunner(
        config=EvaluationConfig(), engine=engine, cp_client=cast(ControlPlaneClient, cp)
    )
    runner._agent_client = cast(AgentClient, agent)
    _init_activity_context(store, cp_client=cp, agent_client=agent)

    async def invoke():
        if engine_kind == "temporal":
            await run_case_for_run(RunCaseInput(run_id=run_id, case_id=case.case_id))
        else:
            assert run is not None
            await runner._execute_run(run)

    await invoke()
    failed = await store.get_case(case.case_id)
    assert failed is not None
    assert failed.trace_json == _trace().model_dump_json()
    assert failed.actual_output == _trace().output
    assert failed.latency_ms == _trace().latency_ms
    assert failed.actual_model_name == _trace().model_name
    assert failed.execution_error is None
    assert failed.outcome != "execution_error"
    assert (
        failed.scoring_errors_json and "case_setup_failed" in failed.scoring_errors_json
    )
    assert failed.status == "error"
    async with engine.begin() as conn:
        _ = await conn.execute(
            text("UPDATE evaluation_run SET snapshot_json=:snapshot WHERE run_id=:id"),
            {"snapshot": saved_snapshot, "id": run_id},
        )
    run = await store.get_run(run_id)
    assert run is not None
    monkeypatch.setattr(scorer, "score_trace", Mock(return_value=([], [])))
    await invoke()
    retried = await store.get_case(case.case_id)
    assert retried is not None and retried.status == "completed"
    assert retried.trace_json == failed.trace_json
    assert agent.evaluate.await_count == 1
    cp.prepare_managed_instance_execution.assert_not_called()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["agent", "judge"])
async def test_cancellation_cannot_replace_the_agent_attempt(
    monkeypatch: pytest.MonkeyPatch, stage: str
):
    import asyncio

    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    agent = AsyncMock()
    agent.evaluate.return_value = _trace()
    if stage == "agent":
        agent.evaluate.side_effect = asyncio.CancelledError()
    monkeypatch.setattr(
        scorer, "score_trace", Mock(side_effect=asyncio.CancelledError())
    )
    with pytest.raises(asyncio.CancelledError):
        await _execute(store, run_id, case.case_id, agent)
    row = await store.get_case(case.case_id)
    assert row is not None and row.execution_session_id is not None
    assert row.trace_available == (stage == "judge")
    agent.evaluate.side_effect = None
    monkeypatch.setattr(scorer, "score_trace", Mock(return_value=([], [])))
    await _execute(store, run_id, case.case_id, agent)
    row = await store.get_case(case.case_id)
    assert row is not None
    assert row.status == ("completed" if stage == "judge" else "error")
    assert agent.evaluate.await_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_report_stops_when_evidence_arrives_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
):
    from fastapi import HTTPException

    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    for i in range(3):
        _ = await store.create_case(
            case_id=f"additional-{i}",
            run_id=run_id,
            external_id=None,
            input="q1",
            expected_output=None,
        )
    rows = await store.list_cases_by_run(run_id)
    for row in rows:
        await store.begin_case_execution(
            row.case_id, run_id=run_id, session_id="attempt-1"
        )
        await store.retain_case_trace(
            row.case_id, run_id=run_id, session_id="attempt-1", trace=_trace()
        )
    # Simulate the preflight snapshot preceding newly committed trace payloads.
    monkeypatch.setattr(store, "retained_trace_bytes", AsyncMock(return_value=0))
    monkeypatch.setattr(
        service, "_REPORT_TRACE_BYTES", len(_trace().model_dump_json().encode("utf-8"))
    )
    original_get = store.get_case
    reads = AsyncMock(wraps=original_get)
    monkeypatch.setattr(store, "get_case", reads)
    with pytest.raises(HTTPException) as error:
        _ = await service.build_run_report(
            run_id, store=store, evaluation_store=evaluations
        )
    assert error.value.status_code == 413
    assert reads.await_count == 2 < len(rows)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_kind", ["temporal", "polling"])
async def test_setup_failure_classifies_unscored_retained_execution_error(
    engine_kind: str,
):
    from fred_evaluation_backend.config.models import EvaluationConfig
    from fred_evaluation_backend.workers.runner import RunRunner
    from fred_evaluation_backend.workers.workflow import RunCaseInput, run_case_for_run
    from tests.test_run_workflow import _init_activity_context  # pyright: ignore[reportUnknownVariableType]

    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    trace = _trace(error="agent tool execution failed")
    await store.begin_case_execution(
        case.case_id, run_id=run_id, session_id="attempt-1"
    )
    await store.retain_case_trace(
        case.case_id, run_id=run_id, session_id="attempt-1", trace=trace
    )
    # Crash after retaining evidence, before classify_outcome/update_case_result.
    cp = AsyncMock()
    _ = await _remove_destination(engine, store, run_id)
    if engine_kind == "temporal":
        _init_activity_context(store, cp_client=cp, agent_client=AsyncMock())
        await run_case_for_run(RunCaseInput(run_id=run_id, case_id=case.case_id))
    else:
        runner = RunRunner(
            config=EvaluationConfig(),
            engine=engine,
            cp_client=cast(ControlPlaneClient, cp),
        )
        run = await store.get_run(run_id)
        assert run is not None
        await runner._execute_run(run)
    failed = await store.get_case(case.case_id)
    run = await store.get_run(run_id)
    assert failed is not None and run is not None
    assert failed.trace_json == trace.model_dump_json()
    assert failed.outcome == "execution_error"
    assert failed.execution_error == trace.error
    assert (
        failed.scoring_errors_json and "case_setup_failed" in failed.scoring_errors_json
    )
    assert run.execution_error_cases == 1
    assert run.scoring_error_cases == 1
    await engine.dispose()


async def _remove_destination(engine: AsyncEngine, store: RunStore, run_id: str) -> str:
    row = await store.get_run(run_id)
    assert row is not None
    original = row.snapshot_json
    snapshot = json.loads(original)
    snapshot["evaluate_url"] = None
    async with engine.begin() as conn:
        _ = await conn.execute(
            text("UPDATE evaluation_run SET snapshot_json=:snapshot WHERE run_id=:id"),
            {"snapshot": json.dumps(snapshot), "id": run_id},
        )
    return original


@pytest.mark.asyncio
async def test_competing_claims_and_trace_writes_preserve_one_attempt():
    import asyncio

    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    claims = await asyncio.gather(
        *(
            store.begin_case_execution(case.case_id, run_id=run_id, session_id=claim)
            for claim in ("claim-a", "claim-b")
        ),
        return_exceptions=True,
    )
    assert sum(result is None for result in claims) == 1
    assert sum(isinstance(result, ValueError) for result in claims) == 1
    claimed = await store.get_case(case.case_id)
    assert claimed is not None and claimed.execution_session_id is not None
    assert (
        await service.get_run_case(run_id, case.case_id, store=store)
    ).execution_session_id is None
    writes = await asyncio.gather(
        *(
            store.retain_case_trace(
                case.case_id,
                run_id=run_id,
                session_id=claimed.execution_session_id,
                trace=_trace(session_id=session),
            )
            for session in ("runtime-a", "runtime-b")
        ),
        return_exceptions=True,
    )
    assert sum(result is None for result in writes) == 1
    assert sum(isinstance(result, ValueError) for result in writes) == 1
    saved = await store.get_case(case.case_id)
    assert saved is not None and saved.trace_json is not None
    assert saved.execution_session_id in ("runtime-a", "runtime-b")
    assert json.loads(saved.trace_json)["session_id"] == saved.execution_session_id
    await engine.dispose()


def test_weaver_alembic_chain_upgrades_existing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from fred_evaluation_backend.config import loader
    from fred_evaluation_backend.config.models import EvaluationConfig

    db = tmp_path / "weaver.db"
    config = EvaluationConfig.model_validate(
        {"storage": {"postgres": {"sqlite_path": str(db)}}}
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(loader, "load_configuration", lambda: config)
    alembic_config = Config()
    alembic_config.set_main_option(
        "script_location", "fred_evaluation_backend/migrations"
    )
    scripts = ScriptDirectory.from_config(alembic_config)
    assert scripts.get_heads() == ["20261123_01"]
    head = scripts.get_revision("head")
    assert head is not None and head.down_revision == "20261111_01"
    command.upgrade(alembic_config, "20261111_01")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        assert "task_id" not in {
            c["name"] for c in inspect(conn).get_columns("evaluation_run")
        }
        _ = conn.execute(
            text(
                "INSERT INTO evaluation_case (case_id, run_id, status, verdict, input, actual_output) VALUES ('old', 'old-run', 'completed', 'passed', 'question', 'retained answer')"
            )
        )
    command.upgrade(alembic_config, "head")
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT version_num FROM alembic_version_evaluation")
            ).scalar_one()
            == "20261123_01"
        )
        assert conn.execute(
            text(
                "SELECT actual_output, trace_json, execution_session_id FROM evaluation_case WHERE case_id='old'"
            )
        ).one() == ("retained answer", None, None)
        assert "task_id" not in {
            c["name"] for c in inspect(conn).get_columns("evaluation_run")
        }
    command.downgrade(alembic_config, "20261111_01")
    with engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT actual_output, raw_trace_ref FROM evaluation_case WHERE case_id='old'"
            )
        ).one() == ("retained answer", None)
    command.upgrade(alembic_config, "head")
    engine.dispose()


@pytest.mark.asyncio
async def test_delayed_failure_cannot_erase_concurrently_retained_answer(
    monkeypatch: pytest.MonkeyPatch,
):
    import asyncio
    from fred_deepeval_cli.core.models import EvaluationMetricResult

    engine, evaluations, store = await _stores()
    _, run_id = await _seed(evaluations, store, "team-1")
    case = (await store.list_cases_by_run(run_id))[0]
    entered_agent, finish_agent = asyncio.Event(), asyncio.Event()
    entered_failure, finish_failure = asyncio.Event(), asyncio.Event()

    async def evaluate(**_kwargs: object) -> EvalTrace:
        entered_agent.set()
        _ = await finish_agent.wait()
        return _trace()

    agent = AsyncMock()
    agent.evaluate.side_effect = evaluate
    metric = EvaluationMetricResult(
        name="answer_relevancy", provider="deepeval", score=1.0, verdict="passed"
    )
    monkeypatch.setattr(scorer, "score_trace", Mock(return_value=([metric], [])))
    original_update = AsyncMock(wraps=store.update_case_result)

    async def delayed_update(case_id: str, **fields: object) -> bool:
        if fields.get("only_if_trace_missing"):
            entered_failure.set()
            _ = await finish_failure.wait()
        return cast(bool, await original_update(case_id, **fields))

    monkeypatch.setattr(store, "update_case_result", delayed_update)
    first = asyncio.create_task(_execute(store, run_id, case.case_id, agent))
    _ = await entered_agent.wait()
    second = asyncio.create_task(_execute(store, run_id, case.case_id, agent))
    _ = await entered_failure.wait()
    finish_agent.set()
    await first
    finish_failure.set()
    await second
    saved = await store.get_case(case.case_id)
    assert saved is not None
    assert saved.status == "completed" and saved.verdict == "passed"
    assert saved.actual_output == _trace().output
    assert saved.trace_json == _trace().model_dump_json()
    assert saved.execution_error is None
    assert agent.evaluate.await_count == 1
    metrics = await store.list_metrics_by_case(case.case_id)
    assert len(metrics) == 1 and metrics[0].score == "1.0"
    events = await store.list_run_events(run_id)
    assert [event.kind for event in events if event.kind.startswith("case_")] == [
        "case_completed"
    ]
    await engine.dispose()
