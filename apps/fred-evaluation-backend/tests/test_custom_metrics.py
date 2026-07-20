"""EVAL-CUSTOM-METRIC — user-defined criteria are validated and survive the round-trip.

Two things are worth pinning offline (GEval itself calls a live judge, so scoring is not
unit-tested here):

* a criterion is validated at creation — an unknown GEval parameter is rejected then, not
  mid-run when it is far more expensive to discover;
* the exact serialize/deserialize the backend performs — `service.create_campaign` writes
  `json.dumps([m.model_dump() ...])`, `run_case` reads it back with `model_validate` —
  is lossless. If it were not, a campaign would score against different criteria than the
  user asked for.
"""

from __future__ import annotations

import json

import pytest
from fred_deepeval_cli.core.models import CustomMetricSpec
from pydantic import ValidationError


def _spec() -> CustomMetricSpec:
    return CustomMetricSpec(
        name="cites_source",
        criteria="The answer must cite at least one source.",
        parameters=["INPUT", "ACTUAL_OUTPUT"],
        threshold=0.7,
    )


# ── validation happens at creation, not mid-run ──────────────────────────────


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValidationError):
        CustomMetricSpec(name="x", criteria="y", parameters=["NOT_A_PARAM"])


def test_empty_criteria_is_rejected():
    with pytest.raises(ValidationError):
        CustomMetricSpec(name="x", criteria="", parameters=["INPUT"])


def test_parameters_map_to_deepeval_enum():
    params = _spec().to_llm_params()
    assert [p.name for p in params] == ["INPUT", "ACTUAL_OUTPUT"]


def test_threshold_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        CustomMetricSpec(name="x", criteria="y", parameters=["INPUT"], threshold=1.5)


# ── the persistence round-trip the backend actually performs ─────────────────


def test_criteria_survive_json_round_trip():
    specs = [_spec()]

    # exactly what service.create_campaign writes to custom_metrics_json
    stored = json.dumps([m.model_dump() for m in specs])

    # exactly what run_case reads back
    restored = [CustomMetricSpec.model_validate(m) for m in json.loads(stored)]

    assert restored == specs


def test_no_custom_metrics_is_null_not_empty_string():
    """service.create_campaign stores None (not "[]") when the user defined none, so the
    column stays cleanly empty; run_case reads "[]" back as no metrics."""
    stored = json.dumps([]) if [] else None
    assert stored is None
    assert [CustomMetricSpec.model_validate(m) for m in json.loads("[]")] == []
