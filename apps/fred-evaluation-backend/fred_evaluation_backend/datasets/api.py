from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fred_core import KeycloakUser, get_config, get_current_user
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.datasets import service
from fred_evaluation_backend.datasets.schemas import (
    CreateDatasetRequest,
    DatasetDetailResponse,
    DatasetListResponse,
)
from fred_evaluation_backend.datasets.store import DatasetStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import EvaluatorErrorResponse
from fred_evaluation_backend.execution.outbound_auth import resolve_interactive_auth

logger = logging.getLogger(__name__)


def _get_dataset_store(request: Request) -> DatasetStore:
    engine: AsyncEngine = request.app.state.db_engine
    return DatasetStore(engine)


def _get_control_plane_client(request: Request) -> ControlPlaneClient:
    return request.app.state.control_plane_client


def build_datasets_router(prefix: str = "") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["Datasets"])

    @router.post(
        "/datasets",
        status_code=201,
        response_model=DatasetDetailResponse,
        responses={
            401: {"model": EvaluatorErrorResponse},
            403: {"model": EvaluatorErrorResponse},
            422: {"description": "Validation Error"},
        },
    )
    async def create_dataset(
        body: CreateDatasetRequest,
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[DatasetStore, Depends(_get_dataset_store)],
        cp_client: Annotated[ControlPlaneClient, Depends(_get_control_plane_client)],
    ) -> DatasetDetailResponse:
        configuration = request.app.dependency_overrides.get(get_config, get_config)()
        auth = resolve_interactive_auth(
            request, user_security_enabled=configuration.security.user.enabled
        )
        return await service.create_dataset(
            body,
            created_by=user.uid,
            store=store,
            control_plane_client=cp_client,
            auth=auth,
        )

    @router.get(
        "/datasets",
        response_model=DatasetListResponse,
        responses={
            401: {"model": EvaluatorErrorResponse},
            403: {"model": EvaluatorErrorResponse},
        },
    )
    async def list_datasets(
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[DatasetStore, Depends(_get_dataset_store)],
        cp_client: Annotated[ControlPlaneClient, Depends(_get_control_plane_client)],
        team_id: str = Query(...),
    ) -> DatasetListResponse:
        configuration = request.app.dependency_overrides.get(get_config, get_config)()
        auth = resolve_interactive_auth(
            request, user_security_enabled=configuration.security.user.enabled
        )
        return await service.list_datasets(
            team_id,
            store=store,
            control_plane_client=cp_client,
            auth=auth,
        )

    return router
