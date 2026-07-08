"""EVAL-02 — a campaign run is a task on the shared bus.

The behaviour worth pinning is the *ordering* and the *failure net*, not the plumbing:

* the bus task is opened **before** the campaign is persisted and before Temporal is
  asked to run anything, so a scheduling failure always has a real ``task_run`` row to
  be recorded against;
* the task is bound to the workflow **after** it starts, because the workflow id does
  not exist before;
* if anything between those two points raises, the task is driven to ``failed``.

That last rule is the whole point of the change. ``reconcile_stale`` skips tasks with no
``execution_id``, so a task opened but never bound is invisible to the sweeper: without
``fail_task`` it would sit "pending" forever, keeping its data alive — the RGPD limbo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fred_evaluation_backend.campaigns import api as campaigns_api
from fred_evaluation_backend.campaigns.api import _start_delay, build_evaluations_router
from fred_evaluation_backend.campaigns.schemas import (
    CampaignCreatedResponse,
    CreateEvaluationCampaignRequest,
    EvaluationExecutionOptions,
)

# ── _start_delay: absolute schedule → relative delay ──────────────────────────


def test_start_delay_is_none_when_not_scheduled():
    assert _start_delay(None) is None


def test_start_delay_is_none_for_a_past_schedule():
    """ "Run now": Temporal rejects a negative delay, so a past date must collapse to None."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert _start_delay(past) is None


def test_start_delay_is_positive_for_a_future_schedule():
    delay = _start_delay(datetime.now(timezone.utc) + timedelta(days=7))
    assert delay is not None
    assert timedelta(days=6) < delay <= timedelta(days=7)


# ── scheduled_for must be unambiguous across the API pod and the worker ───────


def test_scheduled_for_rejects_a_naive_datetime():
    with pytest.raises(ValidationError):
        EvaluationExecutionOptions(scheduled_for=datetime(2030, 1, 1, 9, 0, 0))


def test_scheduled_for_accepts_an_aware_datetime():
    when = datetime(2030, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    assert EvaluationExecutionOptions(scheduled_for=when).scheduled_for == when


# ── the create_campaign route: ordering and failure net ──────────────────────


class _FakeTaskService:
    """Records what the route asks of the bus, so the ordering can be asserted."""

    def __init__(self) -> None:
        self.started: SimpleNamespace | None = None
        self.bound: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    async def start(
        self, request, created_by, team_id=None, target=None, scheduled_for=None
    ):
        self.started = SimpleNamespace(
            request=request,
            created_by=created_by,
            team_id=team_id,
            target=target,
            scheduled_for=scheduled_for,
        )
        return SimpleNamespace(task_id="task-123")

    async def bind_execution(self, task_id: str, *, execution_id: str) -> None:
        self.bound.append((task_id, execution_id))

    async def fail_task(self, task_id: str, message: str) -> bool:
        self.failed.append((task_id, message))
        return True


class _FakeTemporalClient:
    def __init__(self) -> None:
        self.start_kwargs: dict = {}

    async def start_workflow(self, *args, **kwargs):
        self.start_kwargs = kwargs
        return SimpleNamespace(id=kwargs["id"])


class _FakeTemporalProvider:
    def __init__(self, client=None, error: Exception | None = None) -> None:
        self._client = client
        self._error = error

    async def get_client(self):
        if self._error is not None:
            raise self._error
        return self._client


def _endpoint():
    router = build_evaluations_router()
    for route in router.routes:
        if route.path.endswith("/campaigns") and "POST" in route.methods:
            return route.endpoint
    raise AssertionError("POST /campaigns route not found")


def _request(task_service, temporal_provider=None):
    state = SimpleNamespace(
        task_service=task_service,
        temporal_client_provider=temporal_provider,
        temporal_task_queue="evaluation",
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _body(scheduled_for: datetime | None = None) -> CreateEvaluationCampaignRequest:
    return CreateEvaluationCampaignRequest(
        name="rag",
        team_id="team-1",
        target={"kind": "runtime_agent", "runtime_id": "rt", "agent_id": "ag"},
        dataset={"name": "ds", "cases": [{"input": "q?"}]},
        judge_profile_id="judge",
        execution=EvaluationExecutionOptions(scheduled_for=scheduled_for),
    )


@pytest.fixture
def stub_create_campaign(monkeypatch):
    """Neutralise persistence + control-plane: this test is about the bus, not the DB."""
    seen: dict = {}

    async def _fake(
        body, *, created_by, campaign_id, task_id, store, control_plane_client
    ):
        seen.update(campaign_id=campaign_id, task_id=task_id)
        return CampaignCreatedResponse(
            campaign_id=campaign_id, run_id="run-1", task_id=task_id, state="pending"
        )

    monkeypatch.setattr(campaigns_api.service, "create_campaign", _fake)
    return seen


@pytest.mark.asyncio
async def test_campaign_is_bound_to_the_workflow_that_backs_it(stub_create_campaign):
    """Happy path: the task the bus minted is tied to the workflow Temporal started."""
    task_service = _FakeTaskService()
    client = _FakeTemporalClient()
    endpoint = _endpoint()

    result = await endpoint(
        body=_body(),
        request=_request(task_service, _FakeTemporalProvider(client=client)),
        user=SimpleNamespace(uid="alice"),
        store=None,
        cp_client=None,
    )

    # The campaign carries the id the bus minted — not one of its own.
    assert result.task_id == "task-123"
    assert stub_create_campaign["task_id"] == "task-123"

    # The workflow is named after the campaign, and the task points at it.
    workflow_id = f"campaign-eval-{result.campaign_id}"
    assert task_service.bound == [("task-123", workflow_id)]
    assert task_service.failed == []


@pytest.mark.asyncio
async def test_a_scheduled_campaign_carries_its_date_to_bus_and_temporal(
    stub_create_campaign,
):
    """The schedule must reach both the ledger (task_run) and the executor (Temporal)."""
    when = datetime.now(timezone.utc) + timedelta(days=7)
    task_service = _FakeTaskService()
    client = _FakeTemporalClient()

    await _endpoint()(
        body=_body(scheduled_for=when),
        request=_request(task_service, _FakeTemporalProvider(client=client)),
        user=SimpleNamespace(uid="alice"),
        store=None,
        cp_client=None,
    )

    assert task_service.started.scheduled_for == when
    assert client.start_kwargs["start_delay"] is not None
    assert client.start_kwargs["start_delay"] > timedelta(days=6)


@pytest.mark.asyncio
async def test_task_is_failed_when_the_workflow_cannot_be_started(stub_create_campaign):
    """The invariant: no execution behind the task means the sweeper can never close it,
    so the route must close it itself instead of leaving it pending forever."""
    task_service = _FakeTaskService()
    provider = _FakeTemporalProvider(error=RuntimeError("temporal unreachable"))

    with pytest.raises(RuntimeError, match="temporal unreachable"):
        await _endpoint()(
            body=_body(),
            request=_request(task_service, provider),
            user=SimpleNamespace(uid="alice"),
            store=None,
            cp_client=None,
        )

    assert task_service.bound == []
    assert len(task_service.failed) == 1
    failed_task_id, message = task_service.failed[0]
    assert failed_task_id == "task-123"
    assert "temporal unreachable" in message


@pytest.mark.asyncio
async def test_task_is_failed_when_the_campaign_cannot_be_persisted(monkeypatch):
    """Step 2 raising is the same limbo as step 3 raising: the task must not survive it."""

    async def _boom(*args, **kwargs):
        raise ValueError("dataset rejected")

    monkeypatch.setattr(campaigns_api.service, "create_campaign", _boom)
    task_service = _FakeTaskService()

    with pytest.raises(ValueError, match="dataset rejected"):
        await _endpoint()(
            body=_body(),
            request=_request(task_service),
            user=SimpleNamespace(uid="alice"),
            store=None,
            cp_client=None,
        )

    assert task_service.failed and task_service.failed[0][0] == "task-123"
