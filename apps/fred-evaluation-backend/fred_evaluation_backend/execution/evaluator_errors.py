"""The evaluator API's one public error contract.

Owns three things, all producing the same envelope:
- the canonical error envelope (`EvaluatorErrorDetail` / `EvaluatorErrorResponse`)
  and its one code vocabulary (`EvaluatorErrorCode`);
- classification of known Control Plane boundary failures (never a blanket 422 —
  the opaque-resolver problem from EVAL-AUTH-RFC) into that envelope;
- normalization of fred-core's own unstructured 401/403 `HTTPException`s (it runs
  as a dependency *before* any route body, so this app's own resolvers never see
  those failures) into the same envelope, at this app's public API boundary only.

Messages are safe and actionable — never built from the raw target UUID, never
echoing upstream response bodies, bearer tokens, or Authorization headers.

The vocabulary is target-neutral: the resolver serves both `runtime_agent` and
`managed_instance` targets, so codes describe the failure ("forbidden", "not
found") rather than the target kind — one mapping, not one per target type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response

from fred_evaluation_backend.execution.control_plane_client import (
    ControlPlaneInvalidResponseError,
)

logger = logging.getLogger(__name__)

EvaluatorErrorCode = Literal[
    "authentication_required",
    "access_forbidden",
    "control_plane_authentication_failed",
    "target_forbidden",
    "target_not_found",
    "target_unavailable",
    "target_invalid",
    "control_plane_unavailable",
    "control_plane_invalid_response",
    "evaluation_not_found",
]

# Known external-boundary failures the resolver is allowed to reclassify. Anything
# else (RuntimeError, KeyError from local code, programming/config defects) must
# propagate unchanged — never relabelled as a Control Plane failure.
ControlPlaneFailure = (
    httpx.HTTPStatusError
    | httpx.TimeoutException
    | httpx.TransportError
    | ControlPlaneInvalidResponseError
)


class EvaluatorErrorDetail(BaseModel):
    """The `detail` body of an evaluator error response — stable code + safe message."""

    code: EvaluatorErrorCode
    message: str


class EvaluatorErrorResponse(BaseModel):
    """The one canonical, truthful public error envelope: `{"detail": {...}}`.

    `HTTPException(detail=EvaluatorErrorDetail(...).model_dump())` is what
    Starlette actually serializes — this model documents that exact shape in
    OpenAPI. Use it (not `EvaluatorErrorDetail` directly) in route `responses=`.
    """

    detail: EvaluatorErrorDetail


@dataclass(frozen=True)
class _Mapping:
    status_code: int
    code: EvaluatorErrorCode
    message: str


_UNAVAILABLE = _Mapping(
    503,
    "control_plane_unavailable",
    "The Control Plane is temporarily unavailable. Try again later.",
)
_INVALID_RESPONSE = _Mapping(
    502,
    "control_plane_invalid_response",
    "The Control Plane returned an unexpected response.",
)

_UPSTREAM_STATUS_MAP: dict[int, _Mapping] = {
    401: _Mapping(
        401,
        "control_plane_authentication_failed",
        "Your session could not be verified. Please sign in again.",
    ),
    403: _Mapping(
        403,
        "target_forbidden",
        "You do not have permission to use the selected target in this team.",
    ),
    404: _Mapping(
        404,
        "target_not_found",
        "The selected target no longer exists.",
    ),
    409: _Mapping(
        409,
        "target_unavailable",
        "The selected target is currently disabled or unavailable.",
    ),
    422: _Mapping(
        422,
        "target_invalid",
        "The selected target or request could not be prepared.",
    ),
}


def _mapping_for(exc: ControlPlaneFailure) -> tuple[_Mapping, str]:
    """Return (mapping, log_category) for a known Control Plane boundary failure."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        mapping = _UPSTREAM_STATUS_MAP.get(status)
        if mapping is None and 500 <= status < 600:
            return _UNAVAILABLE, f"upstream_5xx({status})"
        if mapping is None:
            return _INVALID_RESPONSE, f"upstream_unmapped({status})"
        return mapping, f"upstream_{status}"

    if isinstance(exc, httpx.TimeoutException):
        return _UNAVAILABLE, "timeout"

    if isinstance(exc, httpx.TransportError):
        return _UNAVAILABLE, "connection"

    # ControlPlaneInvalidResponseError: malformed/unexpected 2xx payload.
    return _INVALID_RESPONSE, f"invalid_response({type(exc).__name__})"


def map_control_plane_error(
    exc: ControlPlaneFailure,
    *,
    operation: str,
    team_id: str,
    target: str,
) -> HTTPException:
    """Classify a known Control Plane boundary failure into a typed HTTPException.

    Logs technical context server-side (operation, team_id, target, category) —
    never bearer tokens, full Authorization headers, or raw upstream response bodies.
    """
    mapping, category = _mapping_for(exc)
    logger.error(
        "[CP-ERROR] operation=%s team_id=%s target=%s category=%s exception_type=%s",
        operation,
        team_id,
        target,
        category,
        type(exc).__name__,
    )
    return HTTPException(
        status_code=mapping.status_code,
        detail=EvaluatorErrorDetail(
            code=mapping.code, message=mapping.message
        ).model_dump(),
    )
def evaluation_not_found_error() -> HTTPException:
    """The selected evaluation does not exist for the caller's team."""
    return HTTPException(
        status_code=404,
        detail=EvaluatorErrorDetail(
            code="evaluation_not_found",
            message="The selected evaluation could not be found.",
        ).model_dump(),
    )


def parse_error_detail(exc: HTTPException) -> EvaluatorErrorDetail:
    """Typed access to the structured `detail` body set by `map_control_plane_error`.

    `HTTPException.detail` is declared `str | None` by Starlette; at runtime it
    holds the dict built above. Validating through the model gives callers
    (error handlers, tests) a typed `code`/`message` instead of indexing `Any`.
    """
    return EvaluatorErrorDetail.model_validate(exc.detail)


# Generic auth-boundary normalization — see `normalize_unstructured_auth_error`.
_GENERIC_AUTH_MAPPING: dict[int, _Mapping] = {
    401: _Mapping(
        401,
        "authentication_required",
        "A valid Authorization Bearer token is required.",
    ),
    403: _Mapping(
        403,
        "access_forbidden",
        "You do not have permission to perform this action.",
    ),
}


async def normalize_unstructured_auth_error(
    request: Request, exc: Exception
) -> Response:
    """Translate an unstructured 401/403 `HTTPException` into the evaluator's
    one canonical error envelope, at the evaluator's own API boundary.

    fred-core's `get_current_user` dependency runs *before* any route body and
    raises its own `HTTPException` with a bare string `detail` (e.g. "No
    authentication token provided", "user_not_accept_gcu") on failure — this
    app's resolvers never see it, so it can't be normalized upstream. This is
    the one place that gap is closed; fred-core's own authentication decisions
    are untouched, and its `WWW-Authenticate` header (etc.) is preserved.

    Every already-structured evaluator error (Control Plane mapping, or any
    future evaluator-raised `HTTPException` with a dict `detail`) and every
    other status code or exception type is delegated to FastAPI's standard
    handling, unchanged.
    """
    # Registered only for HTTPException (see main.py); Starlette never calls this
    # handler with anything else. `Exception` in the signature (not HTTPException)
    # is what `add_exception_handler`'s own typed contract requires.
    assert isinstance(exc, HTTPException)
    mapping = _GENERIC_AUTH_MAPPING.get(exc.status_code)
    if mapping is None or isinstance(exc.detail, dict):
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=mapping.status_code,
        content=EvaluatorErrorResponse(
            detail=EvaluatorErrorDetail(code=mapping.code, message=mapping.message)
        ).model_dump(),
        headers=exc.headers,
    )
