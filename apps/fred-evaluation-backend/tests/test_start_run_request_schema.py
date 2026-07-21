"""StartRunRequest — manual metric selection (replaces automatic profile detection).

`metrics` is now the caller's explicit choice, validated against the same
catalog the API exposes (`runs/metrics_catalog.py`), which deliberately has
no `deepeval`/`fred_deepeval_cli` dependency — the API image never installs
either (see `dockerfiles/Dockerfile-api`). `custom_metrics` mirrors
`fred_deepeval_cli.core.models.CustomMetricSpec`'s shape but only validates
structure here; the stricter DeepEval-enum check on `parameters` stays
worker-side.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fred_evaluation_backend.runs.schemas import StartRunRequest


def _body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "team_id": "team-1",
        "target": {"kind": "managed_instance", "agent_instance_id": "inst-1"},
        "metrics": ["answer_relevancy"],
    }
    base.update(overrides)
    return base


def test_known_metrics_are_accepted():
    request = StartRunRequest.model_validate(
        _body(metrics=["answer_relevancy", "faithfulness", "contextual_precision"])
    )
    assert request.metrics == [
        "answer_relevancy",
        "faithfulness",
        "contextual_precision",
    ]


def test_unknown_metric_is_rejected():
    with pytest.raises(ValidationError):
        _ = StartRunRequest.model_validate(_body(metrics=["not_a_real_metric"]))


def test_empty_metrics_is_rejected():
    """The user must choose at least one metric — there is no automatic fallback."""
    with pytest.raises(ValidationError):
        _ = StartRunRequest.model_validate(_body(metrics=[]))


def test_metrics_is_required():
    body = _body()
    del body["metrics"]
    with pytest.raises(ValidationError):
        _ = StartRunRequest.model_validate(body)


def test_custom_metrics_defaults_to_empty_list():
    request = StartRunRequest.model_validate(_body())
    assert request.custom_metrics == []


def test_custom_metric_accepts_any_parameter_name():
    """Unlike `CustomMetricSpec`, the API-side twin does not check `parameters`
    against DeepEval's `LLMTestCaseParams` enum — that import is worker-only."""
    request = StartRunRequest.model_validate(
        _body(
            custom_metrics=[
                {
                    "name": "cites_source",
                    "criteria": "The answer must cite at least one source.",
                    "parameters": ["NOT_A_REAL_DEEPEVAL_PARAM"],
                    "threshold": 0.7,
                }
            ]
        )
    )
    assert request.custom_metrics[0].parameters == ["NOT_A_REAL_DEEPEVAL_PARAM"]


def test_custom_metric_rejects_empty_criteria():
    with pytest.raises(ValidationError):
        _ = StartRunRequest.model_validate(
            _body(
                custom_metrics=[{"name": "x", "criteria": "", "parameters": ["INPUT"]}]
            )
        )


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        _ = StartRunRequest.model_validate(_body(profile="rag"))
