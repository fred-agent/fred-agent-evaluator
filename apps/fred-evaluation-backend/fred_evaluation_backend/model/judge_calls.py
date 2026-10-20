"""Bounded, measured calls to judge and analysis models.

Every model call goes through `CallPolicy`: a short retry on transient failures only,
a per-profile cap on calls per minute, and one KPI sample and log line per attempt.
Requirements: openspec/specs/judge-calls/spec.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypeVar, override

from fred_core.kpi import BaseKPIWriter, Dims, KPIActor

logger = logging.getLogger(__name__)

T = TypeVar("T")

ACTOR = KPIActor(type="system")
_TRANSIENT_CODES = frozenset({"rate_limited", "timeout", "connection_error"})
_BASE_WAIT_S = 2.0
_MAX_WAIT_S = 30.0
_MESSAGE_CHARS = 300


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallFailure:
    code: str
    http_status: int | None
    exception_type: str
    message: str

    @property
    def transient(self) -> bool:
        if self.code == "provider_http_error":
            return (self.http_status or 0) >= 500
        return self.code in _TRANSIENT_CODES

    @override
    def __str__(self) -> str:
        return f"[{self.code}] {self.exception_type}: {self.message}"


def _timeout_types() -> tuple[type[BaseException], ...]:
    import httpx

    types: list[type[BaseException]] = [TimeoutError, httpx.TimeoutException]
    with suppress(ImportError):
        from litellm.exceptions import Timeout

        types.append(Timeout)
    return tuple(types)


def _connection_types() -> tuple[type[BaseException], ...]:
    import httpx

    types: list[type[BaseException]] = [httpx.TransportError]
    with suppress(ImportError):
        from litellm.exceptions import APIConnectionError

        types.append(APIConnectionError)
    return tuple(types)


def _parse_types() -> tuple[type[BaseException], ...]:
    from pydantic import ValidationError

    types: list[type[BaseException]] = [json.JSONDecodeError, ValidationError]
    with suppress(ImportError):
        from deepeval.errors import DeepEvalError

        types.append(DeepEvalError)
    return tuple(types)


def _http_status(exc: BaseException) -> int | None:
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def describe(exc: BaseException) -> str:
    """One-line, non-empty message: an httpx timeout often has an empty one."""
    import httpx

    text = " ".join(str(exc).split())
    if isinstance(exc, httpx.HTTPStatusError):
        with suppress(Exception):
            text += " body=" + " ".join(exc.response.text.split())
    return text[:_MESSAGE_CHARS] or type(exc).__name__


def classify(exc: BaseException) -> CallFailure:
    """Map a model-call or agent-call exception to the closed error-code set."""
    status = _http_status(exc)
    # Timeouts first: LiteLLM's Timeout carries status 408 and subclasses its
    # connection error, so the generic checks below would misfile it.
    if isinstance(exc, _timeout_types()):
        code = "timeout"
    elif status == 429:
        code = "rate_limited"
    elif status in (401, 403):
        code = "auth_error"
    elif isinstance(exc, _connection_types()):
        code = "connection_error"
    elif status is not None:
        code = "provider_http_error"
    elif isinstance(exc, _parse_types()):
        code = "invalid_json"
    else:
        code = "unknown"
    return CallFailure(
        code=code,
        http_status=status,
        exception_type=type(exc).__name__,
        message=describe(exc),
    )


def retry_delay(attempt: int, exc: BaseException) -> float:
    """Seconds to wait before retrying after failed attempt number `attempt`."""
    with suppress(Exception):
        after = getattr(exc, "response").headers.get("retry-after")
        if after is not None:
            return min(float(after), _MAX_WAIT_S)
    backoff = _BASE_WAIT_S * 2 ** (attempt - 1) + random.uniform(0, 1)  # nosec B311 - jitter
    return min(backoff, _MAX_WAIT_S)


# ---------------------------------------------------------------------------
# Rate cap
# ---------------------------------------------------------------------------


class CallRateLimiter:
    """Spaces calls evenly: at most `max_calls_per_minute` start in any minute.

    Even spacing rather than a token bucket, because a bucket's initial burst is
    exactly what trips a provider quota. Thread-safe: scoring runs in a thread.
    """

    def __init__(
        self,
        max_calls_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval: float = 60.0 / max_calls_per_minute
        self._clock: Callable[[], float] = clock
        self._next_start: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    def reserve(self) -> float:
        """Book the next call slot and return how long to wait for it."""
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            self._next_start = start + self._interval
            return start - now


_limiters: dict[tuple[str, str, int], CallRateLimiter] = {}
_limiters_lock = threading.Lock()


def limiter_for(
    provider: str, model: str, max_calls_per_minute: int
) -> CallRateLimiter:
    """The process-wide limiter of one model profile; judges are rebuilt per case."""
    key = (provider, model, max_calls_per_minute)
    with _limiters_lock:
        limiter = _limiters.get(key)
        if limiter is None:
            limiter = _limiters[key] = CallRateLimiter(max_calls_per_minute)
        return limiter


# ---------------------------------------------------------------------------
# Per-case statistics
# ---------------------------------------------------------------------------


@dataclass
class JudgeCallStats:
    run_id: str | None = None
    case_id: str | None = None
    calls: int = 0
    retries: int = 0
    failures: int = 0
    call_ms: float = 0.0
    throttle_ms: float = 0.0


_case_stats: ContextVar[JudgeCallStats | None] = ContextVar(
    "judge_call_stats", default=None
)


def track_case_calls(run_id: str, case_id: str) -> JudgeCallStats:
    """Collect the judge calls of the current case.

    `asyncio.to_thread` copies the context, so calls made from the scoring thread
    update the object returned here.
    """
    stats = JudgeCallStats(run_id=run_id, case_id=case_id)
    _ = _case_stats.set(stats)
    return stats


# ---------------------------------------------------------------------------
# Call policy
# ---------------------------------------------------------------------------


@dataclass
class CallPolicy:
    model_name: str
    role: str
    max_attempts: int
    limiter: CallRateLimiter
    kpi: BaseKPIWriter
    sleep: Callable[[float], None] = time.sleep
    async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def call(self, fn: Callable[[], T]) -> T:
        attempt = 0
        while True:
            attempt += 1
            self.sleep(self._throttle())
            started = time.perf_counter()
            try:
                result = fn()
            except Exception as exc:
                delay = self._on_failure(exc, attempt, started)
                if delay is None:
                    raise
                self.sleep(delay)
                continue
            self._on_success(started)
            return result

    async def acall(self, fn: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            attempt += 1
            await self.async_sleep(self._throttle())
            started = time.perf_counter()
            try:
                result = await fn()
            except Exception as exc:
                delay = self._on_failure(exc, attempt, started)
                if delay is None:
                    raise
                await self.async_sleep(delay)
                continue
            self._on_success(started)
            return result

    def _throttle(self) -> float:
        wait_s = self.limiter.reserve()
        stats = _case_stats.get()
        if stats is not None:
            stats.throttle_ms += wait_s * 1000.0
        self._emit(
            "eval.judge_throttle_wait_ms",
            wait_s * 1000.0,
            {"model_name": self.model_name, "llm_role": self.role},
        )
        return wait_s

    def _on_success(self, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._record_attempt("ok", "none", elapsed_ms, final_failure=False)

    def _on_failure(self, exc: Exception, attempt: int, started: float) -> float | None:
        """Record a failed attempt; return the wait before a retry, or None to raise."""
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        failure = classify(exc)
        # Annotate rather than wrap: DeepEval's metrics branch on the exception type.
        with suppress(Exception):
            setattr(exc, "error_code", failure.code)
            setattr(exc, "http_status", failure.http_status)
        final = attempt >= self.max_attempts or not failure.transient
        status = "error" if final else "retry"
        self._record_attempt(status, failure.code, elapsed_ms, final_failure=final)
        stats = _case_stats.get()
        logger.log(
            logging.ERROR if final else logging.WARNING,
            "event=judge_call_failed run=%s case=%s role=%s model=%s attempt=%d/%d "
            "status=%s error_code=%s http_status=%s exception_type=%s message=%s",
            stats.run_id if stats else None,
            stats.case_id if stats else None,
            self.role,
            self.model_name,
            attempt,
            self.max_attempts,
            status,
            failure.code,
            failure.http_status,
            failure.exception_type,
            failure.message,
        )
        return None if final else retry_delay(attempt, exc)

    def _record_attempt(
        self, status: str, error_code: str, elapsed_ms: float, *, final_failure: bool
    ) -> None:
        stats = _case_stats.get()
        if stats is not None:
            stats.calls += 1
            stats.call_ms += elapsed_ms
            if status == "retry":
                stats.retries += 1
            elif final_failure:
                stats.failures += 1
        dims: Dims = {
            "model_name": self.model_name,
            "llm_role": self.role,
            "status": status,
            "error_code": error_code,
        }
        with suppress(Exception):
            self.kpi.count("llm.calls_total", dims=dims, actor=ACTOR)
        self._emit("llm.call_latency_ms", elapsed_ms, dims)

    def _emit(self, name: str, value_ms: float, dims: Dims) -> None:
        # Fail-open: a KPI sink problem must never fail a scoring call.
        with suppress(Exception):
            self.kpi.emit(
                name=name,
                type="timer",
                value=value_ms,
                unit="ms",
                dims=dims,
                actor=ACTOR,
            )
