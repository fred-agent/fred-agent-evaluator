from __future__ import annotations

import asyncio
from typing import Annotated, AsyncGenerator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fred_core import KeycloakUser, get_current_user
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.campaigns import service
from fred_evaluation_backend.campaigns.store import EvaluationStore
from fred_evaluation_backend.tasks.models import (
    EvaluationTaskEvent,
    TaskListResponse,
    TaskState,
    TaskSummary,
    campaign_to_event,
    campaign_to_summary,
    map_state,
)


def _get_evaluation_store(request: Request) -> EvaluationStore:
    engine: AsyncEngine = request.app.state.db_engine
    return EvaluationStore(engine)


def build_tasks_router(prefix: str = "") -> APIRouter:
    """Canonical task-event surface over evaluation campaigns.

    A campaign run is one task; `task_id == campaign_id`. State and counters are
    mapped onto the platform-canonical task shape so the frontend drives the
    shared Task components (TaskStateBadge / TaskProgressBar / TaskTray).
    """
    router = APIRouter(prefix=prefix, tags=["Tasks"])

    @router.get("/tasks", response_model=TaskListResponse)
    async def list_tasks(
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
        scope: Literal["user", "team"] = Query("team"),
        team_id: str | None = Query(default=None),
        exclude_terminal: bool = Query(default=False),
    ) -> TaskListResponse:
        if scope == "user":
            rows = await store.list_campaigns_by_creator(user.uid)
        elif team_id:
            rows = await store.list_campaigns_by_team(team_id)
        else:
            rows = []
        summaries = [campaign_to_summary(r) for r in rows]
        if exclude_terminal:
            summaries = [s for s in summaries if not s.state.is_terminal]
        return TaskListResponse(tasks=summaries)

    @router.get("/tasks/{task_id}", response_model=TaskSummary)
    async def get_task(
        task_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> TaskSummary:
        row = await store.get_campaign(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
        return campaign_to_summary(row)

    @router.get("/tasks/{task_id}/latest", response_model=EvaluationTaskEvent)
    async def get_latest_event(
        task_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> EvaluationTaskEvent:
        row = await store.get_campaign(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
        return campaign_to_event(row, seq=0)

    @router.get("/tasks/{task_id}/events")
    async def stream_task_events(
        task_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> StreamingResponse:
        row = await store.get_campaign(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

        async def event_generator() -> AsyncGenerator[str, None]:
            seq = 0
            last: tuple[TaskState, float | None] | None = None
            while True:
                current = await store.get_campaign(task_id)
                if current is None:
                    break
                event = campaign_to_event(current, seq)
                snapshot = (event.state, event.progress)
                if snapshot != last:
                    last = snapshot
                    yield f"id: {seq}\ndata: {event.model_dump_json()}\n\n"
                    seq += 1
                if map_state(current.operational_state).is_terminal:
                    break
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.post("/tasks/{task_id}/cancel", status_code=202)
    async def cancel_task(
        task_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> dict[str, str]:
        await service.cancel_campaign(task_id, store=store)
        return {"task_id": task_id, "state": "cancelling"}

    return router
