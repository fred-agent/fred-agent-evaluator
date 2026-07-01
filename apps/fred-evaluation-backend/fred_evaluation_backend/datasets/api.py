"""HTTP routes for the dataset domain (Phase 2: capture).

`POST /question-sets:import` is **synchronous and interactive**: it reads the caller's
JWT from the incoming request and propagates it to the runtime, so the runtime
authorizes the real user via ReBAC (no M2M, no service authorization). See the
EVAL-DATASET backlog Phase 2.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fred_core import KeycloakUser, get_config, get_current_user
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.config.models import EvaluationConfig
from fred_evaluation_backend.datasets.schemas import QuestionSet
from fred_evaluation_backend.datasets.service import CaptureService
from fred_evaluation_backend.datasets.store import DatasetStore
from fred_evaluation_backend.execution.history_client import HistoryClient

logger = logging.getLogger(__name__)


class ImportQuestionSetRequest(BaseModel):
    team_id: str
    agent_instance_id: str
    period_from: datetime
    period_to: datetime
    keep_threshold: int = Field(default=4, ge=1, le=5)
    extra_filters: dict[str, str] = Field(default_factory=dict)
    max_messages: int | None = None


class QuestionSetListResponse(BaseModel):
    question_sets: list[QuestionSet]


def _get_dataset_store(request: Request) -> DatasetStore:
    engine: AsyncEngine = request.app.state.db_engine
    return DatasetStore(engine)


def _get_history_client(config: EvaluationConfig) -> HistoryClient:
    # Falls back to runtime_base_url when the dedicated history base is unset, so
    # existing setups keep working; configure runtime_history_base_url (with the
    # runtime app prefix) to decouple capture from campaign evaluate_url resolution.
    base_url = (
        config.control_plane.runtime_history_base_url
        or config.control_plane.runtime_base_url
    )
    return HistoryClient(runtime_base_url=base_url)


def build_datasets_router(prefix: str = "") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["Datasets"])

    @router.post("/question-sets:import", response_model=QuestionSet, status_code=201)
    async def import_question_set(
        body: ImportQuestionSetRequest,
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        config: Annotated[EvaluationConfig, Depends(get_config)],
        store: Annotated[DatasetStore, Depends(_get_dataset_store)],
    ) -> QuestionSet:
        # Propagate the caller's bearer token to the runtime (ReBAC authorizes the user).
        bearer_token = request.headers.get("Authorization")
        service = CaptureService(
            store=store, history_client=_get_history_client(config)
        )
        return await service.import_from_history(
            team_id=body.team_id,
            agent_instance_id=body.agent_instance_id,
            period_from=body.period_from,
            period_to=body.period_to,
            created_by=user.uid,
            bearer_token=bearer_token,
            keep_threshold=body.keep_threshold,
            extra_filters=body.extra_filters,
            max_messages=body.max_messages,
        )

    @router.get("/question-sets", response_model=QuestionSetListResponse)
    async def list_question_sets(
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[DatasetStore, Depends(_get_dataset_store)],
        team_id: Annotated[str, Query()],
    ) -> QuestionSetListResponse:
        sets = await store.list_question_sets(team_id)
        return QuestionSetListResponse(question_sets=sets)

    @router.get("/question-sets/{question_set_id}", response_model=QuestionSet)
    async def get_question_set(
        question_set_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[DatasetStore, Depends(_get_dataset_store)],
    ) -> QuestionSet:
        qs = await store.get_question_set(question_set_id)
        if qs is None:
            raise HTTPException(status_code=404, detail="QuestionSet not found")
        return qs

    return router
