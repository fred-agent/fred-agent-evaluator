"""Team-scoped routes the evaluator's own UI calls through Fred's application host.

Fred's gateway forwards `/app-services/evaluation/teams/{team_id}/...` here with
that prefix stripped, so these routes live under `/teams/{team_id}/...` with no
`/evaluation/v1` base: they are mounted beside the existing router, not under it,
and the existing surface is untouched.

Two gates apply on every route, and neither implies the other:
- `require_entitled` — the Control Plane says `team_id` may use this application
  (which also proves the caller is a member of it);
- ownership — the evaluation or run named in the path belongs to `team_id`.
  Without it, being entitled in one team would open every other team's runs by
  id; a resource of another team answers 404, exactly like a missing one.

The choice routes (agent instances, model profiles, metrics) read what the
UI offers when starting a run; the frame cannot call the Control Plane itself,
so this service does, with the caller's own token.

The routes are thin: the team comes from the path, never from the body
(`EvaluationDocument`, `RunSpec`), and everything else is the same service code
the existing surface runs. No SSE here — the host's request bridge buffers
responses, so the UI polls `GET /runs/{run_id}` instead.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Query, Request, Response
from fred_core import KeycloakUser, get_current_user
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from fred_evaluation_backend.evaluations import service as evaluation_service
from fred_evaluation_backend.evaluations.schemas import (
    CreateEvaluationRequest,
    EvaluationDetailResponse,
    EvaluationDocument,
    EvaluationListResponse,
)
from fred_evaluation_backend.evaluations.store import EvaluationStore
from fred_evaluation_backend.execution.control_plane_client import (
    ControlPlaneClient,
    TeamAgentInstance,
    TeamModelProfile,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    EvaluatorErrorResponse,
    evaluation_not_found_error,
    map_control_plane_error,
    run_not_found_error,
)
from fred_evaluation_backend.execution.outbound_auth import OutboundAuth
from fred_evaluation_backend.hosted.entitlement import (
    CONTROL_PLANE_FAILURES,
    get_control_plane_client,
    require_entitled,
)
from fred_evaluation_backend.runs import service as run_service
from fred_evaluation_backend.runs.api import launch_run, write_run_analysis
from fred_evaluation_backend.runs.metrics_catalog import (
    BUILTIN_METRIC_IDS,
    EXPECTED_OUTPUT_METRIC_IDS,
)
from fred_evaluation_backend.runs.schemas import (
    EvaluationCaseListResponse,
    EvaluationCaseResponse,
    EvaluationRun,
    EvaluationRunListResponse,
    EvaluationRunSummaryResponse,
    RunAnalysisResponse,
    RunCreatedResponse,
    RunReportResponse,
    RunSpec,
)
from fred_evaluation_backend.runs.store import RunStore


def _get_evaluation_store(request: Request) -> EvaluationStore:
    engine: AsyncEngine = request.app.state.db_engine
    return EvaluationStore(engine)


def _get_run_store(request: Request) -> RunStore:
    engine: AsyncEngine = request.app.state.db_engine
    return RunStore(engine)


Entitled = Annotated[OutboundAuth, Depends(require_entitled)]
CurrentUser = Annotated[KeycloakUser, Depends(get_current_user)]
Evaluations = Annotated[EvaluationStore, Depends(_get_evaluation_store)]
Runs = Annotated[RunStore, Depends(_get_run_store)]
ControlPlane = Annotated[ControlPlaneClient, Depends(get_control_plane_client)]

_GATED: dict[int | str, dict[str, Any]] = {
    401: {"model": EvaluatorErrorResponse},
    403: {"model": EvaluatorErrorResponse},
    404: {"model": EvaluatorErrorResponse},
    502: {"model": EvaluatorErrorResponse},
    503: {"model": EvaluatorErrorResponse},
}


async def _require_team_evaluation(
    evaluation_id: str, team_id: str, store: EvaluationStore
) -> None:
    row = await store.get_evaluation(evaluation_id)
    if row is None or row.team_id != team_id:
        raise evaluation_not_found_error()


async def _require_team_run(run_id: str, team_id: str, store: RunStore) -> None:
    row = await store.get_run(run_id)
    if row is None or row.team_id != team_id:
        raise run_not_found_error()


class MetricChoice(BaseModel):
    """A built-in metric a run can be scored against."""

    metric_id: str
    # Scored against `expected_output`: skipped on cases without one.
    requires_expected_output: bool


_T = TypeVar("_T")


async def _from_control_plane(
    call: Awaitable[_T], *, operation: str, team_id: str
) -> _T:
    try:
        return await call
    except CONTROL_PLANE_FAILURES as exc:
        raise map_control_plane_error(
            exc, operation=operation, team_id=team_id, target=f"team={team_id}"
        ) from exc


def build_hosted_router() -> APIRouter:
    router = APIRouter(prefix="/teams/{team_id}", tags=["Evaluation app"])

    @router.get("/evaluations", response_model=EvaluationListResponse, responses=_GATED)
    async def list_evaluations(
        team_id: str,
        auth: Entitled,
        store: Evaluations,
        cp_client: ControlPlane,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        sort: str | None = Query(
            default=None,
            description="Sort as 'field:direction' (created_at, name, version), e.g. 'created_at:desc'.",
        ),
        q: str | None = Query(
            default=None, description="Case-insensitive search on the evaluation name."
        ),
    ) -> EvaluationListResponse:
        return await evaluation_service.list_evaluations(
            team_id,
            offset=offset,
            limit=limit,
            sort=sort,
            q=q,
            store=store,
            control_plane_client=cp_client,
            auth=auth,
        )

    @router.post(
        "/evaluations",
        status_code=201,
        response_model=EvaluationDetailResponse,
        responses={**_GATED, 409: {"description": "Version already exists"}},
    )
    async def create_evaluation(
        team_id: str,
        document: EvaluationDocument,
        auth: Entitled,
        user: CurrentUser,
        store: Evaluations,
        cp_client: ControlPlane,
    ) -> EvaluationDetailResponse:
        return await evaluation_service.create_evaluation(
            CreateEvaluationRequest(team_id=team_id, **document.model_dump()),
            created_by=user.uid,
            store=store,
            control_plane_client=cp_client,
            auth=auth,
        )

    @router.get(
        "/evaluations/{evaluation_id}",
        response_model=EvaluationDetailResponse,
        responses=_GATED,
    )
    async def get_evaluation(
        team_id: str, evaluation_id: str, auth: Entitled, store: Evaluations
    ) -> EvaluationDetailResponse:
        await _require_team_evaluation(evaluation_id, team_id, store)
        return await evaluation_service.get_evaluation(evaluation_id, store=store)

    @router.delete(
        "/evaluations/{evaluation_id}",
        status_code=204,
        response_class=Response,
        responses={**_GATED, 409: {"model": EvaluatorErrorResponse}},
    )
    async def delete_evaluation(
        team_id: str,
        evaluation_id: str,
        auth: Entitled,
        store: Evaluations,
        run_store: Runs,
        cp_client: ControlPlane,
    ) -> Response:
        await _require_team_evaluation(evaluation_id, team_id, store)
        await evaluation_service.delete_evaluation(
            evaluation_id,
            store=store,
            run_store=run_store,
            control_plane_client=cp_client,
            auth=auth,
        )
        return Response(status_code=204)

    @router.post(
        "/evaluations/{evaluation_id}/runs",
        status_code=202,
        response_model=RunCreatedResponse,
        responses={**_GATED, 422: {"model": EvaluatorErrorResponse}},
    )
    async def start_run(
        team_id: str,
        evaluation_id: str,
        spec: RunSpec,
        request: Request,
        auth: Entitled,
        user: CurrentUser,
        store: Runs,
        evaluation_store: Evaluations,
        cp_client: ControlPlane,
    ) -> RunCreatedResponse:
        # start_run itself refuses an evaluation of another team (404).
        return await launch_run(
            request,
            evaluation_id=evaluation_id,
            team_id=team_id,
            spec=spec,
            created_by=user.uid,
            store=store,
            evaluation_store=evaluation_store,
            cp_client=cp_client,
            auth=auth,
        )

    @router.get(
        "/evaluations/{evaluation_id}/runs",
        response_model=EvaluationRunListResponse,
        responses=_GATED,
    )
    async def list_runs(
        team_id: str,
        evaluation_id: str,
        auth: Entitled,
        store: Runs,
        evaluation_store: Evaluations,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        sort: str | None = Query(
            default=None,
            description="Sort as 'field:direction' (created_at, verdict, operational_state), e.g. 'created_at:desc'.",
        ),
    ) -> EvaluationRunListResponse:
        await _require_team_evaluation(evaluation_id, team_id, evaluation_store)
        return await run_service.list_runs(
            evaluation_id, offset=offset, limit=limit, sort=sort, store=store
        )

    @router.get(
        "/evaluations/{evaluation_id}/runs/summary",
        response_model=EvaluationRunSummaryResponse,
        responses=_GATED,
    )
    async def get_runs_summary(
        team_id: str,
        evaluation_id: str,
        auth: Entitled,
        store: Runs,
        evaluation_store: Evaluations,
    ) -> EvaluationRunSummaryResponse:
        await _require_team_evaluation(evaluation_id, team_id, evaluation_store)
        return await run_service.get_run_summary(evaluation_id, store=store)

    @router.get("/runs/{run_id}", response_model=EvaluationRun, responses=_GATED)
    async def get_run(
        team_id: str, run_id: str, auth: Entitled, store: Runs
    ) -> EvaluationRun:
        await _require_team_run(run_id, team_id, store)
        return await run_service.get_run(run_id, store=store)

    @router.delete(
        "/runs/{run_id}",
        status_code=204,
        response_class=Response,
        responses=_GATED,
    )
    async def delete_run(
        team_id: str, run_id: str, auth: Entitled, store: Runs
    ) -> Response:
        await _require_team_run(run_id, team_id, store)
        await run_service.delete_run(run_id, store=store)
        return Response(status_code=204)

    @router.get(
        "/runs/{run_id}/cases",
        response_model=EvaluationCaseListResponse,
        responses=_GATED,
    )
    async def list_run_cases(
        team_id: str,
        run_id: str,
        auth: Entitled,
        store: Runs,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> EvaluationCaseListResponse:
        await _require_team_run(run_id, team_id, store)
        return await run_service.list_run_cases(
            run_id, offset=offset, limit=limit, store=store
        )

    @router.get(
        "/runs/{run_id}/cases/{case_id}",
        response_model=EvaluationCaseResponse,
        responses=_GATED,
    )
    async def get_run_case(
        team_id: str, run_id: str, case_id: str, auth: Entitled, store: Runs
    ) -> EvaluationCaseResponse:
        await _require_team_run(run_id, team_id, store)
        return await run_service.get_run_case(run_id, case_id, store=store)

    @router.get(
        "/runs/{run_id}/report", response_model=RunReportResponse, responses=_GATED
    )
    async def get_run_report(
        team_id: str,
        run_id: str,
        auth: Entitled,
        store: Runs,
        evaluation_store: Evaluations,
        cp_client: ControlPlane,
    ) -> RunReportResponse:
        await _require_team_run(run_id, team_id, store)
        return await run_service.build_run_report(
            run_id,
            store=store,
            evaluation_store=evaluation_store,
            control_plane_client=cp_client,
            auth=auth,
        )

    @router.post("/runs/{run_id}/cancel", status_code=202, responses=_GATED)
    async def cancel_run(
        team_id: str, run_id: str, auth: Entitled, store: Runs
    ) -> dict[str, str]:
        await _require_team_run(run_id, team_id, store)
        await run_service.cancel_run(run_id, store=store)
        return {"run_id": run_id, "state": "cancelled"}

    @router.post(
        "/runs/{run_id}/analyze",
        response_model=RunAnalysisResponse,
        responses={**_GATED, 409: {"description": "Run not completed yet"}},
    )
    async def analyze(
        team_id: str, run_id: str, request: Request, auth: Entitled, store: Runs
    ) -> RunAnalysisResponse:
        await _require_team_run(run_id, team_id, store)
        return await write_run_analysis(request, run_id, store=store)

    @router.get(
        "/agent-instances", response_model=list[TeamAgentInstance], responses=_GATED
    )
    async def list_agent_instances(
        team_id: str, auth: Entitled, cp_client: ControlPlane
    ) -> list[TeamAgentInstance]:
        return await _from_control_plane(
            cp_client.list_team_agent_instances(team_id=team_id, auth=auth),
            operation="list_team_agent_instances",
            team_id=team_id,
        )

    @router.get(
        "/model-profiles", response_model=list[TeamModelProfile], responses=_GATED
    )
    async def list_model_profiles(
        team_id: str, auth: Entitled, cp_client: ControlPlane
    ) -> list[TeamModelProfile]:
        return await _from_control_plane(
            cp_client.list_team_model_profiles(team_id=team_id, auth=auth),
            operation="list_team_model_profiles",
            team_id=team_id,
        )

    @router.get("/metrics", response_model=list[MetricChoice], responses=_GATED)
    async def list_metrics(team_id: str, auth: Entitled) -> list[MetricChoice]:
        return [
            MetricChoice(
                metric_id=metric_id,
                requires_expected_output=metric_id in EXPECTED_OUTPUT_METRIC_IDS,
            )
            for metric_id in sorted(BUILTIN_METRIC_IDS)
        ]

    return router
