"""Judge and analysis model calls: retries, rate cap, error codes, KPIs.

The bounded model runs against a faked `litellm.completion`, so each test counts the
requests that would reach the provider.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from datetime import datetime
from types import SimpleNamespace
from typing import override

import httpx
import litellm
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
import pytest
from deepeval.errors import DeepEvalError
from fred_core.common import ModelConfiguration
from fred_core.kpi import Dims, KPIActor, NoOpKPIWriter

from fred_evaluation_backend.model import judge_calls
from fred_evaluation_backend.model.factory import build_judge_model
from fred_evaluation_backend.model.judge_calls import (
    CallRateLimiter,
    classify,
    limiter_for,
    track_case_calls,
)


class RecordingKPI(NoOpKPIWriter):
    """Keeps the KPI samples a test emits."""

    def __init__(self) -> None:
        self.counts: list[tuple[str, dict[str, object]]] = []
        self.timers: list[tuple[str, float, dict[str, object]]] = []

    @override
    def count(
        self,
        name: str,
        inc: int = 1,
        *,
        dims: Dims | None = None,
        labels: Iterable[str] | None = None,
        actor: KPIActor,
    ) -> None:
        self.counts.append((name, dict(dims or {})))

    @override
    def emit(
        self,
        *,
        name: str,
        type: str,
        value: float | None = None,
        unit: str | None = None,
        dims: Dims | None = None,
        cost: dict[str, object] | None = None,
        quantities: dict[str, object] | None = None,
        labels: Iterable[str] | None = None,
        trace: dict[str, object] | None = None,
        timestamp: datetime | None = None,
        actor: KPIActor,
    ) -> None:
        self.timers.append((name, value or 0.0, dict(dims or {})))


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )


def _rate_limited():
    return RateLimitError("slow down", llm_provider="mistral", model="m")


def _timeout():
    return Timeout("took too long", model="m", llm_provider="mistral")


def _judge(monkeypatch: pytest.MonkeyPatch, outcomes, *, kpi=None, max_attempts=2):
    """A bounded judge whose provider plays `outcomes` in order; returns (judge, calls)."""
    calls: list[dict[str, object]] = []

    def fake_completion(**params):
        calls.append(params)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return _response(outcome)

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")  # pragma: allowlist secret
    judge = build_judge_model(
        ModelConfiguration(
            provider="litellm",
            name="mistral/mistral-small-latest",
            settings={
                "api_key_env": "MISTRAL_API_KEY",  # pragma: allowlist secret
                "max_attempts": max_attempts,
            },
        ),
        kpi=kpi,
    )
    judge._call_policy.sleep = lambda _s: None
    return judge, calls


# --- retries ---------------------------------------------------------------


def test_rate_limited_once_then_answered_sends_two_requests(
    monkeypatch: pytest.MonkeyPatch,
):
    kpi = RecordingKPI()
    judge, calls = _judge(monkeypatch, [_rate_limited(), "the verdict"], kpi=kpi)

    output, _cost = judge.generate("prompt")

    assert output == "the verdict"
    assert len(calls) == 2
    statuses = [
        (d["status"], d["error_code"]) for n, d in kpi.counts if n == "llm.calls_total"
    ]
    assert statuses == [("retry", "rate_limited"), ("ok", "none")]
    assert all(d["llm_role"] == "judge" for _n, d in kpi.counts)


def test_persistent_timeout_sends_exactly_max_attempts(monkeypatch: pytest.MonkeyPatch):
    judge, calls = _judge(monkeypatch, [_timeout()], max_attempts=3)

    with pytest.raises(Timeout) as raised:
        judge.generate("prompt")

    assert len(calls) == 3
    assert getattr(raised.value, "error_code") == "timeout"


def test_invalid_credentials_are_not_retried(monkeypatch: pytest.MonkeyPatch):
    auth = AuthenticationError("bad key", llm_provider="mistral", model="m")
    judge, calls = _judge(monkeypatch, [auth])

    with pytest.raises(AuthenticationError) as raised:
        judge.generate("prompt")

    assert len(calls) == 1
    assert getattr(raised.value, "error_code") == "auth_error"


def test_unparseable_answer_is_not_retried(monkeypatch: pytest.MonkeyPatch):
    from pydantic import BaseModel

    class Verdict(BaseModel):
        verdict: str

    judge, calls = _judge(monkeypatch, ["this is not json"])

    with pytest.raises(DeepEvalError) as raised:
        judge.generate_with_schema("prompt", schema=Verdict)

    assert len(calls) == 1
    assert getattr(raised.value, "error_code") == "invalid_json"


def test_async_path_follows_the_same_policy(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []

    async def fake_acompletion(**params):
        calls.append(params)
        if len(calls) == 1:
            raise _rate_limited()
        return _response("async verdict")

    judge, _ = _judge(monkeypatch, ["unused"])
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def no_sleep(_s):
        return None

    judge._call_policy.async_sleep = no_sleep

    output, _cost = asyncio.run(judge.a_generate("prompt"))

    assert output == "async verdict"
    assert len(calls) == 2


# --- classification --------------------------------------------------------


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://agent/evaluate")
    response = httpx.Response(status, request=request, text='{"detail":"boom"}')
    return httpx.HTTPStatusError("failed", request=request, response=response)


@pytest.mark.parametrize(
    ("exc", "code", "status", "transient"),
    [
        (_rate_limited(), "rate_limited", 429, True),
        (_timeout(), "timeout", 408, True),
        (httpx.ReadTimeout(""), "timeout", None, True),
        (
            ServiceUnavailableError("down", llm_provider="p", model="m"),
            "provider_http_error",
            503,
            True,
        ),
        (
            BadRequestError("bad", model="m", llm_provider="p"),
            "provider_http_error",
            400,
            False,
        ),
        (
            APIConnectionError("refused", llm_provider="p", model="m"),
            "connection_error",
            500,
            True,
        ),
        (httpx.ConnectError("refused"), "connection_error", None, True),
        (_http_error(403), "auth_error", 403, False),
        (_http_error(502), "provider_http_error", 502, True),
        (DeepEvalError("invalid JSON"), "invalid_json", None, False),
        (ValueError("something else"), "unknown", None, False),
    ],
)
def test_failures_map_to_the_closed_set(exc, code, status, transient):
    failure = classify(exc)
    assert (failure.code, failure.http_status, failure.transient) == (
        code,
        status,
        transient,
    )


def test_an_empty_message_is_replaced_by_the_exception_type():
    failure = classify(httpx.ReadTimeout(""))
    assert failure.message == "ReadTimeout"
    assert str(failure) == "[timeout] ReadTimeout: ReadTimeout"


def test_an_http_error_message_carries_the_response_body():
    assert 'body={"detail":"boom"}' in classify(_http_error(502)).message


# --- rate cap --------------------------------------------------------------


def test_no_minute_holds_more_calls_than_the_cap():
    now = [0.0]
    limiter = CallRateLimiter(10, clock=lambda: now[0])
    starts = []
    for _ in range(22):
        wait = limiter.reserve()
        starts.append(now[0] + wait)
        now[0] += wait  # the caller sleeps, then calls

    for first in starts:
        in_window = [s for s in starts if first <= s < first + 60.0]
        assert len(in_window) <= 10


def test_concurrent_callers_share_one_limiter():
    limiter = CallRateLimiter(60)  # one slot per second
    waits: list[float] = []
    lock = threading.Lock()

    def book():
        for _ in range(5):
            wait = limiter.reserve()
            with lock:
                waits.append(wait)

    threads = [threading.Thread(target=book) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # 20 bookings, one second apart: the last waits about 19 s.
    assert len(waits) == 20
    assert max(waits) == pytest.approx(19.0, abs=0.5)


def test_judges_rebuilt_per_case_share_the_profile_limiter():
    assert limiter_for("litellm", "m", 30) is limiter_for("litellm", "m", 30)
    assert limiter_for("litellm", "m", 30) is not limiter_for("litellm", "other", 30)


def test_throttle_wait_is_recorded_but_not_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    kpi = RecordingKPI()
    judge, _calls = _judge(monkeypatch, ["a", "b"], kpi=kpi)
    judge._call_policy.limiter = CallRateLimiter(1)  # 60 s between calls

    judge.generate("first")
    judge.generate("second")

    waits = [v for n, v, _d in kpi.timers if n == "eval.judge_throttle_wait_ms"]
    assert waits[0] == pytest.approx(0.0, abs=50)
    assert waits[1] == pytest.approx(60_000.0, rel=0.01)
    assert {d["status"] for n, d in kpi.counts} == {"ok"}


# --- per-case statistics ---------------------------------------------------


def test_calls_from_the_scoring_thread_land_in_the_case_stats(
    monkeypatch: pytest.MonkeyPatch,
):
    judge, _calls = _judge(monkeypatch, [_rate_limited(), "ok"])

    async def score_one_case():
        stats = track_case_calls("run-1", "case-1")
        await asyncio.to_thread(judge.generate, "prompt")
        return stats

    stats = asyncio.run(score_one_case())

    assert (stats.calls, stats.retries, stats.failures) == (2, 1, 0)


def test_judge_call_failure_log_names_run_case_and_code(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    judge, _calls = _judge(monkeypatch, [_timeout()], max_attempts=1)

    async def score_one_case():
        track_case_calls("run-1", "case-1")
        with pytest.raises(Timeout):
            await asyncio.to_thread(judge.generate, "prompt")

    with caplog.at_level("ERROR", logger=judge_calls.__name__):
        asyncio.run(score_one_case())

    messages = [r.getMessage() for r in caplog.records]
    line = next(m for m in messages if "judge_call_failed" in m)
    assert "run=run-1 case=case-1" in line
    assert "error_code=timeout" in line
    assert "exception_type=Timeout" in line


# --- analysis model --------------------------------------------------------


def test_run_analysis_is_counted_with_the_analysis_role(
    monkeypatch: pytest.MonkeyPatch,
):
    from fred_evaluation_backend.execution.analysis_client import AnalysisClient

    async def fake_acompletion(**_params):
        return _response('{"summary": "fine", "risk_level": "low"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")  # pragma: allowlist secret
    kpi = RecordingKPI()
    client = AnalysisClient(
        ModelConfiguration(
            provider="litellm",
            name="mistral/mistral-small-latest",
            settings={
                "api_key_env": "MISTRAL_API_KEY",  # pragma: allowlist secret
                "max_calls_per_minute": 600,
            },
        ),
        kpi=kpi,
    )

    asyncio.run(
        client.analyze(
            evaluation_name="e",
            profile="rag",
            verdict="passed",
            total_cases=0,
            passed_cases=0,
            failed_cases=0,
            insufficient_cases=0,
            metric_averages={},
            cases=[],
        )
    )

    roles = [
        (d["llm_role"], d["status"]) for n, d in kpi.counts if n == "llm.calls_total"
    ]
    assert roles == [("analysis", "ok")]
