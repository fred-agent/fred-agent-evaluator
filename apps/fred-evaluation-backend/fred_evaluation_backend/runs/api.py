from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Annotated, AsyncGenerator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from fred_core import KeycloakUser, get_config, get_current_user
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.analysis_client import (
    CaseDetail,
    CaseMetricDetail,
)
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient
from fred_evaluation_backend.execution.evaluator_errors import EvaluatorErrorResponse
from fred_evaluation_backend.execution.outbound_auth import resolve_interactive_auth
from fred_evaluation_backend.runs import service
from fred_evaluation_backend.runs.schemas import (
    EvaluationCaseListResponse,
    EvaluationCaseResponse,
    EvaluationRun,
    RunAnalysisResponse,
    RunAnalysisResult,
    RunCreatedResponse,
    RunReportResponse,
    StartRunRequest,
)
from fred_evaluation_backend.runs.store import RunStore

logger = logging.getLogger(__name__)


class TelemetryInfoResponse(BaseModel):
    enabled: bool
    langfuse_session_url: str | None = None


class TelemetrySessionResponse(BaseModel):
    available: bool
    url: str | None = None


def _get_run_store(request: Request) -> RunStore:
    engine: AsyncEngine = request.app.state.db_engine
    return RunStore(engine)


def _get_evaluation_catalog_store(request: Request) -> EvaluationStore:
    engine: AsyncEngine = request.app.state.db_engine
    return EvaluationStore(engine)


def _get_control_plane_client(request: Request) -> ControlPlaneClient:
    return request.app.state.control_plane_client


def _get_temporal_client_provider(request: Request):
    return getattr(request.app.state, "temporal_client_provider", None)


async def _resolve_langfuse_session_url(config) -> str | None:
    obs = config.observability
    if obs.tracer != "langfuse":
        return None
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        return None
    base = obs.langfuse.host.rstrip("/")
    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{base}/api/public/projects",
                headers={"Authorization": f"Basic {credentials}"},
            )
            resp.raise_for_status()
            projects = resp.json().get("data", [])
            if projects:
                project_id = projects[0]["id"]
                return f"{base}/project/{project_id}/sessions"
    except Exception as exc:
        logger.warning("[TELEMETRY] could not resolve Langfuse project: %s", exc)
    return None


def build_evaluations_router(prefix: str = "") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["Evaluations"])

    @router.post(
        "/evaluations/{evaluation_id}/runs",
        status_code=202,
        response_model=RunCreatedResponse,
        responses={
            401: {"model": EvaluatorErrorResponse},
            403: {"model": EvaluatorErrorResponse},
            404: {"model": EvaluatorErrorResponse},
            422: {"model": EvaluatorErrorResponse},
            502: {"model": EvaluatorErrorResponse},
            503: {"model": EvaluatorErrorResponse},
        },
    )
    async def start_run(
        evaluation_id: str,
        body: StartRunRequest,
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
        evaluation_store: Annotated[
            EvaluationStore, Depends(_get_evaluation_catalog_store)
        ],
        cp_client: Annotated[ControlPlaneClient, Depends(_get_control_plane_client)],
    ) -> RunCreatedResponse:
        configuration = request.app.dependency_overrides.get(get_config, get_config)()
        auth = resolve_interactive_auth(
            request, user_security_enabled=configuration.security.user.enabled
        )
        result = await service.start_run(
            evaluation_id=evaluation_id,
            team_id=body.team_id,
            target=body.target,
            created_by=user.uid,
            store=store,
            evaluation_store=evaluation_store,
            control_plane_client=cp_client,
            auth=auth,
            profile=service._DEFAULT_PROFILE,
            judge_profile_id=service.default_judge_profile_id(
                configuration.worker.judge_profiles
            ),
        )

        temporal_provider = _get_temporal_client_provider(request)
        if temporal_provider is not None:
            from fred_evaluation_backend.workers.workflow import RunInput, RunWorkflow

            task_queue = (
                getattr(request.app.state, "temporal_task_queue", "evaluation")
                or "evaluation"
            )
            client = await temporal_provider.get_client()
            await client.start_workflow(
                RunWorkflow.run,
                RunInput(run_id=result.run_id),
                id=f"run-eval-{result.run_id}",
                task_queue=task_queue,
            )

        return result

    @router.get("/evaluations/{evaluation_id}/runs", response_model=list[EvaluationRun])
    async def list_runs(
        evaluation_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> list[EvaluationRun]:
        return await service.list_runs(evaluation_id, store=store)

    @router.get("/runs/{run_id}", response_model=EvaluationRun)
    async def get_run(
        run_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> EvaluationRun:
        return await service.get_run(run_id, store=store)

    @router.get("/runs/{run_id}/cases", response_model=EvaluationCaseListResponse)
    async def list_run_cases(
        run_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> EvaluationCaseListResponse:
        return await service.list_run_cases(
            run_id, offset=offset, limit=limit, store=store
        )

    @router.get("/runs/{run_id}/cases/{case_id}", response_model=EvaluationCaseResponse)
    async def get_run_case(
        run_id: str,
        case_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> EvaluationCaseResponse:
        return await service.get_run_case(run_id, case_id, store=store)

    @router.get(
        "/runs/{run_id}/report",
        response_model=RunReportResponse,
        responses={
            401: {"model": EvaluatorErrorResponse},
            403: {"model": EvaluatorErrorResponse},
            404: {"model": EvaluatorErrorResponse},
        },
    )
    async def get_run_report(
        run_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
        evaluation_store: Annotated[
            EvaluationStore, Depends(_get_evaluation_catalog_store)
        ],
    ) -> RunReportResponse:
        return await service.build_run_report(
            run_id, store=store, evaluation_store=evaluation_store
        )

    @router.get("/runs/{run_id}/events")
    async def stream_run_events(
        run_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> StreamingResponse:
        if await store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

        async def event_generator() -> AsyncGenerator[str, None]:
            last_seq = -1
            while True:
                events = await store.list_run_events(run_id, after_seq=last_seq)
                for event in events:
                    last_seq = event.seq
                    data = json.dumps(
                        {
                            "seq": event.seq,
                            "kind": event.kind,
                            "payload": json.loads(event.payload_json)
                            if event.payload_json
                            else None,
                        }
                    )
                    yield f"data: {data}\n\n"
                run_row = await store.get_run(run_id)
                if run_row and run_row.operational_state in (
                    "succeeded",
                    "failed",
                    "cancelled",
                ):
                    break
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.post("/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(
        run_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> dict:
        await service.cancel_run(run_id, store=store)
        return {"run_id": run_id, "state": "cancelled"}

    @router.delete("/runs/{run_id}", status_code=204, response_class=Response)
    async def delete_run(
        run_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> Response:
        await service.delete_run(run_id, store=store)
        return Response(status_code=204)

    @router.get("/telemetry/session/{run_id}", response_model=TelemetrySessionResponse)
    async def get_telemetry_session(
        run_id: str,
        request: Request,
        store: Annotated[RunStore, Depends(_get_run_store)],
        user: Annotated[KeycloakUser, Depends(get_current_user)],
    ) -> TelemetrySessionResponse:
        if await store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

        config = request.app.dependency_overrides.get(get_config, get_config)()
        obs = config.observability
        if obs.tracer != "langfuse":
            return TelemetrySessionResponse(available=False)
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
        if not public_key or not secret_key:
            return TelemetrySessionResponse(available=False)
        base = obs.langfuse.host.rstrip("/")
        credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{base}/api/public/sessions/{run_id}",
                    headers={"Authorization": f"Basic {credentials}"},
                )
                if resp.status_code == 200:
                    projects_resp = await client.get(
                        f"{base}/api/public/projects",
                        headers={"Authorization": f"Basic {credentials}"},
                    )
                    projects_resp.raise_for_status()
                    projects = projects_resp.json().get("data", [])
                    if projects:
                        project_id = projects[0]["id"]
                        url = f"{base}/project/{project_id}/sessions/{run_id}"
                        return TelemetrySessionResponse(available=True, url=url)
        except Exception as exc:
            logger.warning("[TELEMETRY] session check failed: %s", exc)
        return TelemetrySessionResponse(available=False)

    @router.get("/telemetry", response_model=TelemetryInfoResponse)
    async def get_telemetry(
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
    ) -> TelemetryInfoResponse:
        config = request.app.dependency_overrides.get(get_config, get_config)()
        langfuse_session_url = await _resolve_langfuse_session_url(config)
        return TelemetryInfoResponse(
            enabled=config.observability.tracer == "langfuse",
            langfuse_session_url=langfuse_session_url,
        )

    @router.post("/runs/{run_id}/analyze", response_model=RunAnalysisResponse)
    async def analyze_run(
        run_id: str,
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[RunStore, Depends(_get_run_store)],
    ) -> RunAnalysisResponse:
        run = await store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        if run.analysis_json:
            stored = json.loads(run.analysis_json)
            return RunAnalysisResponse(
                run_id=run_id,
                analysis=RunAnalysisResult(**stored["analysis"]),
                cached=True,
            )

        analysis_client = getattr(request.app.state, "analysis_client", None)
        if analysis_client is None:
            raise HTTPException(
                status_code=503, detail="Analysis service not configured"
            )

        if run.operational_state != "completed":
            raise HTTPException(status_code=409, detail="Run is not completed yet")

        metric_averages: dict[str, float] = {}
        if run.metric_averages_json:
            metric_averages = json.loads(run.metric_averages_json)

        snapshot = json.loads(run.snapshot_json) if run.snapshot_json else {}
        run_name = snapshot.get("evaluation_name", run_id)

        raw_cases = await store.list_cases_by_run(run_id, limit=10000)
        all_metrics = await store.list_metrics_by_run(run_id)
        metrics_by_case: dict[str, list] = {}
        for m in all_metrics:
            metrics_by_case.setdefault(m.case_id, []).append(m)

        cases: list[CaseDetail] = [
            CaseDetail(
                case_id=c.case_id,
                input=c.input,
                verdict=c.verdict,
                metrics=[
                    CaseMetricDetail(
                        name=m.name,
                        score=float(m.score) if m.score is not None else None,
                        verdict=m.verdict,
                        explanation=m.explanation,
                    )
                    for m in metrics_by_case.get(c.case_id, [])
                ],
            )
            for c in raw_cases
        ]

        analysis_text = await analysis_client.analyze(
            evaluation_name=run_name,
            profile=run.profile,
            verdict=run.verdict,
            total_cases=run.total_cases,
            passed_cases=run.passed_cases,
            failed_cases=run.failed_cases,
            metric_averages=metric_averages,
            cases=cases,
        )

        analysis_data = json.loads(analysis_text)

        for field in ("strengths", "weaknesses", "recommendations"):
            analysis_data[field] = [
                item
                if isinstance(item, str)
                else item.get("task")
                or item.get("recommendation")
                or item.get("description")
                or next(iter(item.values()), str(item))
                for item in analysis_data.get(field, [])
            ]

        analysis_result = RunAnalysisResult(**analysis_data)

        await store.update_run_analysis(
            run_id=run_id,
            analysis_json=json.dumps({"analysis": analysis_data}),
        )

        return RunAnalysisResponse(
            run_id=run_id,
            analysis=analysis_result,
            cached=False,
        )

    return router


_get_evaluation_store = _get_run_store
