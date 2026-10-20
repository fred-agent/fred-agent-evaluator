"""What the worker exposes about a case: KPIs, error logs, the summary line.

`execute_and_score_case` runs against an in-memory fake store and a patched
`score_trace`; the judge is the real bounded model on a faked `litellm.completion`.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import pytest
from fred_core.kpi import KPIWriter
from fred_core.kpi.prometheus_kpi_store import PrometheusKPIStore
from fred_deepeval_cli.core import scorer
from fred_deepeval_cli.core.models import EvaluationMetricResult
from prometheus_client import REGISTRY

from fred_evaluation_backend.config.models import EvaluationConfig
from fred_evaluation_backend.telemetry import kpi as kpi_module
from fred_evaluation_backend.workers.activities import execute_and_score_case
from tests.test_judge_calls import RecordingKPI, _judge, _rate_limited


class _FakeStore:
    def __init__(self) -> None:
        self.case_results: list[dict[str, object]] = []
        self.metrics: list[dict[str, object]] = []

    async def update_case_result(self, case_id, **fields):
        self.case_results.append(fields)

    async def delete_metrics_by_case(self, case_id):
        self.metrics.clear()

    async def create_metric_result(self, **fields):
        self.metrics.append(fields)

    async def create_run_event(self, run_id, *, kind, payload_json):
        return None


class _Agent:
    def __init__(self, error: Exception | None = None) -> None:
        self._error: Exception | None = error

    async def evaluate(self, **kwargs):
        if self._error is not None:
            raise self._error
        from fred_sdk.contracts.eval import EvalTrace

        return EvalTrace(
            session_id=kwargs["session_id"],
            agent_id="agent-1",
            input=kwargs["input"],
            latency_ms=10,
            output="the answer",
        )


async def _run_case(*, store, agent, judge, kpi):
    await execute_and_score_case(
        case_id="case-1",
        run_id="run-1",
        created_by="alice",
        input="question",
        expected_output=None,
        agent_id="agent-1",
        session_id="s-1",
        evaluate_url="http://agent/evaluate",
        team_id="team-1",
        profile="default",
        judge=judge,
        metrics=["answer_relevancy"],
        store=store,
        agent_client=agent,
        kpi=kpi,
    )


def _summary(caplog: pytest.LogCaptureFixture) -> str:
    return next(
        r.getMessage()
        for r in caplog.records
        if "event=eval_case_done" in r.getMessage()
    )


# --- 2.1 exporter -----------------------------------------------------------


def test_worker_serves_metrics_on_the_configured_address(
    monkeypatch: pytest.MonkeyPatch,
):
    started: list[tuple[int, str]] = []
    monkeypatch.setattr(
        kpi_module, "start_http_server", lambda port, addr: started.append((port, addr))
    )
    config = EvaluationConfig.model_validate(
        {
            "observability": {
                "kpi": {
                    "prometheus": {"enabled": True, "address": "0.0.0.0", "port": 9000},
                    "opensearch": {"enabled": False},
                }
            }
        }
    )

    kpi_module.start_kpi(config, service_name="fred-evaluation-worker")

    assert started == [(9000, "0.0.0.0")]


# --- 2.2 scoring off the loop, agent errors, summary ------------------------


def test_the_event_loop_runs_while_a_case_is_scored(monkeypatch: pytest.MonkeyPatch):
    def slow_score(*_args, **_kwargs):
        time.sleep(0.5)
        return [], []

    monkeypatch.setattr(scorer, "score_trace", slow_score)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    async def scenario():
        task = asyncio.create_task(ticker())
        await _run_case(
            store=_FakeStore(), agent=_Agent(), judge=object(), kpi=RecordingKPI()
        )
        task.cancel()

    asyncio.run(scenario())

    assert ticks >= 5


def test_agent_timeout_with_empty_message_is_logged_and_counted(
    caplog: pytest.LogCaptureFixture,
):
    kpi = RecordingKPI()
    store = _FakeStore()

    with caplog.at_level(logging.INFO):
        asyncio.run(
            _run_case(
                store=store,
                agent=_Agent(httpx.ReadTimeout("")),
                judge=object(),
                kpi=kpi,
            )
        )

    line = next(
        r.getMessage() for r in caplog.records if "agent_call_failed" in r.getMessage()
    )
    assert "error_code=timeout" in line and "exception_type=ReadTimeout" in line
    assert "message=ReadTimeout" in line
    assert store.case_results[-1]["execution_error"] == (
        "[timeout] ReadTimeout: ReadTimeout"
    )
    agent = [d for n, _v, d in kpi.timers if n == "eval.agent_call_latency_ms"]
    assert agent == [
        {"status": "error", "error_code": "timeout", "http_status": "none"}
    ]
    assert ("eval.cases_total", {"status": "error"}) in kpi.counts
    assert "verdict=error" in _summary(caplog)


def test_summary_line_sets_agent_and_judge_load_side_by_side(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    judge, _calls = _judge(monkeypatch, [_rate_limited(), "ok", "ok"])

    def score_with_two_judge_calls(*_args, judge, **_kwargs):
        judge.generate("statements")
        judge.generate("verdicts")
        return [
            EvaluationMetricResult(
                name="AnswerRelevancyMetric",
                provider="deepeval",
                score=1.0,
                verdict="passed",
            )
        ], []

    monkeypatch.setattr(scorer, "score_trace", score_with_two_judge_calls)
    kpi = RecordingKPI()

    with caplog.at_level(logging.INFO):
        asyncio.run(_run_case(store=_FakeStore(), agent=_Agent(), judge=judge, kpi=kpi))

    line = _summary(caplog)
    assert "run=run-1 case=case-1 verdict=passed" in line
    assert "agent_ms=" in line and "agent_ms=none" not in line
    assert "judge_calls=3 judge_retries=1 judge_failures=0" in line
    assert "judge_ms=" in line and "throttle_ms=" in line
    assert ("eval.cases_total", {"status": "passed"}) in kpi.counts


# --- 2.3 metric errors ------------------------------------------------------


def test_one_metric_error_is_logged_and_the_other_metrics_are_stored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def one_failing_metric(*_args, **_kwargs):
        return [
            EvaluationMetricResult(
                name="AnswerRelevancyMetric",
                provider="deepeval",
                score=0.9,
                verdict="passed",
            ),
            EvaluationMetricResult(
                name="FaithfulnessMetric",
                provider="deepeval",
                score=None,
                verdict="error",
                error="[rate_limited] RateLimitError: slow down",
                error_code="rate_limited",
            ),
        ], ["FaithfulnessMetric: [rate_limited] RateLimitError: slow down"]

    monkeypatch.setattr(scorer, "score_trace", one_failing_metric)
    store = _FakeStore()

    with caplog.at_level(logging.INFO):
        asyncio.run(
            _run_case(store=store, agent=_Agent(), judge=object(), kpi=RecordingKPI())
        )

    errors = [
        r.getMessage() for r in caplog.records if "event=metric_error" in r.getMessage()
    ]
    assert len(errors) == 1
    assert "metric=FaithfulnessMetric error_code=rate_limited" in errors[0]
    assert "run=run-1 case=case-1" in errors[0]
    assert [m["name"] for m in store.metrics] == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
    ]
    assert "metric_errors=1" in _summary(caplog)


# --- 2.4 no identifiers in Prometheus labels --------------------------------


def test_prometheus_labels_carry_no_run_case_or_team_id(
    monkeypatch: pytest.MonkeyPatch,
):
    judge, _calls = _judge(monkeypatch, ["ok"])
    writer = KPIWriter(PrometheusKPIStore())
    judge._call_policy.kpi = writer

    def score_once(*_args, judge, **_kwargs):
        judge.generate("prompt")
        return [], []

    monkeypatch.setattr(scorer, "score_trace", score_once)
    asyncio.run(_run_case(store=_FakeStore(), agent=_Agent(), judge=judge, kpi=writer))

    seen = set()
    for family in REGISTRY.collect():
        for sample in family.samples:
            seen.update(sample.labels.values())
    assert {"judge", "ok"} <= seen  # the run did reach Prometheus
    assert not {"run-1", "case-1", "team-1", "alice", "s-1"} & seen
