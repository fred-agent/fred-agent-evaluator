"""Generated OpenAPI must describe the real evaluator error envelope.

`HTTPException(detail=EvaluatorErrorDetail(...).model_dump())` serializes as
`{"detail": {"code": ..., "message": ...}}`. The OpenAPI `responses=` on
`POST /evaluations/{evaluation_id}/runs` must document exactly that shape via
`EvaluatorErrorResponse`
— not the bare `EvaluatorErrorDetail` (which would document `{"code", "message"}`
at the top level, a body FastAPI never actually returns).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from fred_evaluation_backend.runs.api import build_evaluations_router


def _openapi() -> dict[str, Any]:
    app = FastAPI()
    app.include_router(build_evaluations_router())
    return app.openapi()


def test_evaluator_error_response_schema_wraps_detail():
    schema = _openapi()
    envelope = schema["components"]["schemas"]["EvaluatorErrorResponse"]
    assert set(envelope["required"]) == {"detail"}
    # `detail` must ref the code+message model, not be a bare string or inline object —
    # this is what makes the envelope match what Starlette actually serializes.
    assert envelope["properties"]["detail"]["$ref"] == (
        "#/components/schemas/EvaluatorErrorDetail"
    )

    detail = schema["components"]["schemas"]["EvaluatorErrorDetail"]
    assert set(detail["properties"]) == {"code", "message"}


def test_documented_error_statuses_reference_the_envelope_not_the_bare_detail():
    schema = _openapi()
    responses = schema["paths"]["/evaluations/{evaluation_id}/runs"]["post"]["responses"]

    for status in ("401", "403", "404", "502", "503"):
        content_schema = responses[status]["content"]["application/json"]["schema"]
        assert content_schema["$ref"] == "#/components/schemas/EvaluatorErrorResponse"


def test_422_documents_both_possible_bodies_via_one_of():
    schema = _openapi()
    responses = schema["paths"]["/evaluations/{evaluation_id}/runs"]["post"]["responses"]
    content_schema = responses["422"]["content"]["application/json"]["schema"]
    assert content_schema["$ref"] == "#/components/schemas/EvaluatorErrorResponse"
