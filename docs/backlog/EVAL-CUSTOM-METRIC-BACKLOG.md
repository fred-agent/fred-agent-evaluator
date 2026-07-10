# Evaluation — User-defined metrics via GEval

**Status**: [ ] in progress
**Priority**: medium
**RFC**: `docs/rfc/EVAL-CUSTOM-METRIC-RFC.md`
**Track**: `EVAL-CUSTOM-METRIC`

## Goal

Let a user attach their own natural-language evaluation criteria when creating a
campaign (e.g. a business criterion: "the answer must cover the RAO — operational
context, cause analysis, recommendation"). Each criterion is scored by DeepEval's
`GEval`, alongside the built-in metrics.

---

## Package — libs/fred-deepeval-cli

- [x] Add a `CustomMetricSpec` model (`core/models.py`): `name`, `criteria`,
      `parameters: list[str]`, `threshold` — validates param names against `LLMTestCaseParams`
- [x] `score_trace` accepts `custom_metrics: list[CustomMetricSpec]` and appends one
      `GEval` per spec (map param names → `LLMTestCaseParams`)
- [x] Bump package version `0.1.3` → `0.1.4`

## Backend — fred-evaluation-backend

- [x] `CustomMetric` field on `CreateEvaluationCampaignRequest` (`campaigns/schemas.py`) —
      re-exports the package's `CustomMetricSpec`, single source of truth
- [x] `custom_metrics_json` column on the campaign model (`campaigns/models.py`)
- [x] Alembic migration for the new column (`e7a9c1b3d5f2`)
- [x] Persist criteria in `store.create_campaign` + `service.create_campaign`
- [x] `run_case` reads the campaign's criteria and threads them into
      `execute_and_score_case` → `score_trace` (`workers/workflow.py`, `workers/activities.py`)
- [x] Tests: criteria validation + JSON round-trip (`tests/test_custom_metrics.py`).
      GEval scoring itself hits a live judge → verified by a live campaign, not unit tests

## Frontend — fred (separate, later)

- [ ] Criteria editor in the campaign creation form
- [ ] Show each custom metric's score/verdict/explanation in results
