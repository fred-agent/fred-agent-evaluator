# Evaluation — User-defined metrics via GEval + manual built-in metric selection

**Status**: [x] backend done (2026-07-21) — frontend pending
**Priority**: medium
**RFC**: `docs/rfc/EVAL-CUSTOM-METRIC-RFC.md`
**Track**: `EVAL-CUSTOM-METRIC`

## Goal

Let a user attach their own natural-language evaluation criteria when starting a
run (e.g. a business criterion: "the answer must cover the RAO — operational
context, cause analysis, recommendation"), scored by DeepEval's `GEval` — and
let them explicitly choose which built-in metrics run, instead of a profile
auto-detected from agent tags (which had no visibility into which tools a
general-purpose agent had manually attached).

> Note: this backlog predates the "campaign" → "evaluation"/"run" rename
> (EVAL-04). `campaigns/*` below is now `runs/*`.

---

## Package — libs/fred-deepeval-cli

- [x] Add a `CustomMetricSpec` model (`core/models.py`): `name`, `criteria`,
      `parameters: list[str]`, `threshold` — validates param names against `LLMTestCaseParams`
- [x] `score_trace` accepts `custom_metrics: list[CustomMetricSpec]` and appends one
      `GEval` per spec (map param names → `LLMTestCaseParams`)
- [x] `score_trace` accepts an explicit `metrics: list[str]` (2026-07-21) — replaces the
      profile cascade for built-ins when given; `None` keeps the old cascade for the CLI
      standalone path. `contextual_precision`/`contextual_recall` without `expected_output`
      now report `"skipped"` instead of erroring.
- [ ] Bump package version `0.1.3` → `0.1.4` — not done (see RFC §8: the new `metrics`
      param is additive/optional, judged non-breaking for existing callers)

## Backend — fred-evaluation-backend

- [x] `custom_metrics` field on `StartRunRequest` (`runs/schemas.py`) — **not** a re-export
      of the package's `CustomMetricSpec`: a structurally-equivalent
      `CustomMetricSpecInput` instead, because the API image never installs
      `deepeval`/`fred-deepeval-cli` (`dockerfiles/Dockerfile-api`) and `CustomMetricSpec`'s
      validator imports `deepeval.test_case.LLMTestCaseParams`. The stricter parameter-name
      check happens worker-side instead.
- [x] `metrics: list[str]` field on `StartRunRequest`, required + non-empty, validated
      against `runs/metrics_catalog.py` (2026-07-21) — the manual built-in selection.
- [x] `custom_metrics_json` column on the run model (`runs/models.py`) — **corrected
      2026-07-21**: this column existed since the initial schema but was never actually
      wired — `service.start_run` hardcoded `custom_metrics_json=None`. Now persists the
      request's `custom_metrics`.
- [x] `metrics_json` column on the run model (2026-07-21, migration
      `20260721_01_add_run_metrics_json.py`)
- [x] Persist `metrics`/`custom_metrics` in `store.create_run` + `service.start_run`
- [x] `run_case_for_run` (Temporal) and `RunRunner._execute_run` (in-memory) both read the
      run's `metrics_json`/`custom_metrics_json` and thread them into
      `execute_and_score_case` → `score_trace` (`workers/workflow.py`,
      `workers/runner.py`, `workers/activities.py`)
- [x] Tests: criteria validation + JSON round-trip (`tests/test_custom_metrics.py`);
      `StartRunRequest` schema validation for both fields
      (`tests/test_start_run_request_schema.py`); explicit-metrics `score_trace` behavior
      incl. the `"skipped"` verdict (`libs/fred-deepeval-cli/tests/test_deepeval_runner.py`).
      GEval scoring itself hits a live judge → verified by a live run, not unit tests

## Frontend — fred (separate, tracked on that repo's own issue)

- [ ] Metric-selection UI in `RunCreate.tsx` — checkbox list of the 5 built-in ids +
      a custom-criterion add form (no `Checkbox`/`MultiSelect` atom exists yet)
- [ ] Regenerate the evaluation OpenAPI client to pick up `metrics`/`custom_metrics` on
      `StartRunRequest`
- [ ] Show each custom metric's score/verdict/explanation in results (already returned by
      `EvaluationCaseResponse.metrics`, just needs surfacing)
