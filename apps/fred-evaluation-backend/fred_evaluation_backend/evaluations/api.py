from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fred_core import KeycloakUser, get_config, get_current_user
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.evaluations import service
from fred_evaluation_backend.evaluations.schemas import (
    CreateEvaluationRequest,
    EvaluationDetailResponse,
    EvaluationListResponse,
)
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import EvaluatorErrorResponse
from fred_evaluation_backend.execution.outbound_auth import resolve_interactive_auth

logger = logging.getLogger(__name__)


def _get_evaluation_catalog_store(request: Request) -> EvaluationStore:
    engine: AsyncEngine = request.app.state.db_engine
    return EvaluationStore(engine)


def _get_control_plane_client(request: Request) -> ControlPlaneClient:
    return request.app.state.control_plane_client


def build_evaluation_catalog_router(prefix: str = "") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["Evaluations"])

    @router.post(
        "/evaluations",
        status_code=201,
        response_model=EvaluationDetailResponse,
        responses={
            401: {"model": EvaluatorErrorResponse},
            403: {"model": EvaluatorErrorResponse},
            422: {"description": "Validation Error"},
        },
    )
    async def create_evaluation(
        body: CreateEvaluationRequest,
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_catalog_store)],
        cp_client: Annotated[ControlPlaneClient, Depends(_get_control_plane_client)],
    ) -> EvaluationDetailResponse:
        configuration = request.app.dependency_overrides.get(get_config, get_config)()
        auth = resolve_interactive_auth(
            request, user_security_enabled=configuration.security.user.enabled
        )
        return await service.create_evaluation(
            body,
            created_by=user.uid,
            store=store,
            control_plane_client=cp_client,
            auth=auth,
        )

    @router.get(
        "/evaluations",
        response_model=EvaluationListResponse,
        responses={
            401: {"model": EvaluatorErrorResponse},
            403: {"model": EvaluatorErrorResponse},
        },
    )
    async def list_evaluations(
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_catalog_store)],
        cp_client: Annotated[ControlPlaneClient, Depends(_get_control_plane_client)],
        team_id: str = Query(...),
    ) -> EvaluationListResponse:
        configuration = request.app.dependency_overrides.get(get_config, get_config)()
        auth = resolve_interactive_auth(
            request, user_security_enabled=configuration.security.user.enabled
        )
        return await service.list_evaluations(
            team_id,
            store=store,
            control_plane_client=cp_client,
            auth=auth,
        )

    return router


build_datasets_router = build_evaluation_catalog_router
_get_dataset_store = _get_evaluation_catalog_store
