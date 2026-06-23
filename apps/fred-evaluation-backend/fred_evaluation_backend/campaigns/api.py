from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from fred_core import KeycloakUser, get_current_user
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.campaigns import service
from fred_evaluation_backend.campaigns.schemas import (
    CampaignAnalysisResponse,
    CampaignAnalysisResult,
    CampaignCreatedResponse,
    CreateEvaluationCampaignRequest,
    EvaluationCampaignListResponse,
    EvaluationCampaignResponse,
    EvaluationCaseListResponse,
    EvaluationCaseResponse,
)
from fred_evaluation_backend.execution.analysis_client import CaseDetail, CaseMetricDetail
from fred_evaluation_backend.campaigns.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import ControlPlaneClient


def _get_evaluation_store(request: Request) -> EvaluationStore:
    engine: AsyncEngine = request.app.state.db_engine
    return EvaluationStore(engine)


def _get_control_plane_client(request: Request) -> ControlPlaneClient:
    return request.app.state.control_plane_client


def build_evaluations_router(prefix: str = "") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["Evaluations"])

    @router.post(
        "/campaigns",
        status_code=202,
        response_model=CampaignCreatedResponse,
    )
    async def create_campaign(
        body: CreateEvaluationCampaignRequest,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
        cp_client: Annotated[ControlPlaneClient, Depends(_get_control_plane_client)],
    ) -> CampaignCreatedResponse:
        return await service.create_campaign(
            body,
            created_by=user.uid,
            store=store,
            control_plane_client=cp_client,
        )

    @router.get(
        "/campaigns",
        response_model=EvaluationCampaignListResponse,
    )
    async def list_campaigns(
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
        team_id: str = Query(...),
    ) -> EvaluationCampaignListResponse:
        campaigns = await service.list_campaigns(team_id, store=store)
        return EvaluationCampaignListResponse(campaigns=campaigns, total=len(campaigns))

    @router.get(
        "/campaigns/{campaign_id}",
        response_model=EvaluationCampaignResponse,
    )
    async def get_campaign(
        campaign_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> EvaluationCampaignResponse:
        return await service.get_campaign(campaign_id, store=store)

    @router.get(
        "/campaigns/{campaign_id}/cases",
        response_model=EvaluationCaseListResponse,
    )
    async def list_cases(
        campaign_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> EvaluationCaseListResponse:
        return await service.list_cases(
            campaign_id, offset=offset, limit=limit, store=store
        )

    @router.get(
        "/campaigns/{campaign_id}/cases/{case_id}",
        response_model=EvaluationCaseResponse,
    )
    async def get_case(
        campaign_id: str,
        case_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> EvaluationCaseResponse:
        cases = await service.list_cases(campaign_id, store=store)
        case = next((c for c in cases.cases if c.case_id == case_id), None)
        if case is None:
            raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
        return case

    @router.get("/campaigns/{campaign_id}/events")
    async def stream_events(
        campaign_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> StreamingResponse:
        await service.get_campaign(campaign_id, store=store)

        async def event_generator() -> AsyncGenerator[str, None]:
            last_seq = -1
            while True:
                events = await store.list_events(campaign_id, after_seq=last_seq)
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
                campaign_row = await store.get_campaign(campaign_id)
                if campaign_row and campaign_row.operational_state in (
                    "succeeded",
                    "failed",
                    "cancelled",
                ):
                    break
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.post("/campaigns/{campaign_id}/cancel", status_code=202)
    async def cancel_campaign(
        campaign_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> dict:
        await service.cancel_campaign(campaign_id, store=store)
        return {"campaign_id": campaign_id, "state": "cancelled"}

    @router.delete("/campaigns/{campaign_id}", status_code=204, response_class=Response)
    async def delete_campaign(
        campaign_id: str,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> Response:
        await service.delete_campaign(campaign_id, store=store)
        return Response(status_code=204)

    @router.post("/campaigns/{campaign_id}/analyze", response_model=CampaignAnalysisResponse)
    async def analyze_campaign(
        campaign_id: str,
        request: Request,
        user: Annotated[KeycloakUser, Depends(get_current_user)],
        store: Annotated[EvaluationStore, Depends(_get_evaluation_store)],
    ) -> CampaignAnalysisResponse:
        campaign = await store.get_campaign(campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")

        if campaign.analysis_json:
            stored = json.loads(campaign.analysis_json)
            return CampaignAnalysisResponse(
                campaign_id=campaign_id,
                analysis=CampaignAnalysisResult(**stored["analysis"]),
                cached=True,
            )

        analysis_client = getattr(request.app.state, "analysis_client", None)
        if analysis_client is None:
            raise HTTPException(status_code=503, detail="Analysis service not configured")

        metric_averages: dict[str, float] = {}
        if campaign.metric_averages_json:
            metric_averages = json.loads(campaign.metric_averages_json)

        if campaign.operational_state != "completed":
            raise HTTPException(status_code=409, detail="Campaign is not completed yet")

        # Build per-case details with metric breakdowns
        raw_cases = await store.list_cases_by_campaign(campaign_id, limit=10000)
        all_metrics = await store.list_metrics_by_campaign(campaign_id)
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
            campaign_name=campaign.name,
            profile=campaign.profile,
            verdict=campaign.verdict,
            total_cases=campaign.total_cases,
            passed_cases=campaign.passed_cases,
            failed_cases=campaign.failed_cases,
            metric_averages=metric_averages,
            cases=cases,
        )

        analysis_data = json.loads(analysis_text)

        # Normalize fields that Mistral sometimes returns as objects instead of strings
        for field in ("strengths", "weaknesses", "recommendations"):
            analysis_data[field] = [
                item if isinstance(item, str)
                else item.get("task") or item.get("recommendation") or item.get("description") or next(iter(item.values()), str(item))
                for item in analysis_data.get(field, [])
            ]

        analysis_result = CampaignAnalysisResult(**analysis_data)

        await store.update_campaign_analysis(
            campaign_id=campaign_id,
            analysis_json=json.dumps({"analysis": analysis_data}),
        )

        return CampaignAnalysisResponse(
            campaign_id=campaign_id,
            analysis=analysis_result,
            cached=False,
        )

    return router
