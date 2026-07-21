# RFC EVAL-CUSTOM-METRIC — User-defined evaluation criteria via GEval

**Status:** accepted — implemented (2026-07-21). Scope extended to include §5's
first non-goal (manual selection of the built-in metrics) — see §9.
**Author:** Odelia Cohen
**Reviewers:** Dimitri Tombroff, Evaluation backend owner
**Track:** `EVAL-CUSTOM-METRIC`
**Related:** `EVAL-DATASET-RFC.md` (evaluation creation payload — historically
"campaign", renamed since; see §9), `EVAL-SCHEDULING-BUS-RFC.md` (run
lifecycle), `libs/fred-deepeval-cli` (`score_trace`)

> **Vocabulary note:** this RFC predates the "campaign" → "evaluation"/"run"
> rename (EVAL-04). Where it says `campaign`, read `evaluation` (the
> definition) or `run` (an execution) — e.g. `campaigns/schemas.py` is now
> `runs/schemas.py`, `CreateEvaluationCampaignRequest` is `StartRunRequest`.
> Left as-is below for historical accuracy; §9 gives the current names.

---

## 1. Decision requested

Agree that a user creating a campaign may attach **their own evaluation criteria, written
in plain language** (e.g. *"the answer must cite a source"*, *"the tone must stay
formal"*), and that these are scored by DeepEval's **`GEval`** metric alongside the
built-in ones — rather than being limited to the fixed set the profile hard-codes.

---

## 2. Current state and the gap

Scoring is entirely hard-coded in `fred_deepeval_cli.core.scorer.score_trace`. The metric
list is fixed and chosen by a cascade of `if`s on the profile:

- every case gets `AnswerRelevancyMetric`;
- `rag` + retrieval context adds `Faithfulness` and `ContextualRelevancy`;
- with an expected output, `ContextualPrecision` and `ContextualRecall`.

The profile itself is not user-chosen either — `resolve_profile` derives it from the
agent's tags (`rag`/`sql`/`workflow`) or falls back to `default`.

**The gap:** the user cannot express *what* to evaluate. Five DeepEval metrics, no way to
add a sixth of their own. Any criterion outside relevance/faithfulness/context (citation,
tone, format, refusal to hallucinate a figure) is unreachable today.

---

## 3. Proposal — carry natural-language criteria to GEval

`GEval` is a DeepEval metric that takes a criterion in natural language plus the list of
parameters it may inspect (`INPUT`, `ACTUAL_OUTPUT`, `EXPECTED_OUTPUT`, `TOOLS_CALLED`, …)
and returns a score, a verdict, and an explanation — exactly the shape `score_trace`
already produces. So the algorithm exists; what is missing is the pipe that carries the
user's criterion from the form to `GEval`. Nothing about the output model
(`EvaluationMetricResult`) or the storage (`evaluation_metric`) needs to change.

### 3.1 The chain, end to end (two repos)

1. **API payload** (`campaigns/schemas.py`) — add a field to
   `CreateEvaluationCampaignRequest`, alongside `judge_profile_id`:
   ```python
   custom_metrics: list[CustomMetric] = []

   class CustomMetric(BaseModel):
       name: str                       # shown in results, e.g. "cites_source"
       criteria: str                   # the plain-language rule
       parameters: list[GEvalParam]    # which fields GEval may read
       threshold: float = 0.5
   ```
2. **Persistence** (`campaigns/{service,store,models}.py`) — store the list on the
   campaign, so the worker (a separate process) can read it back. One JSON column, like
   `metric_averages_json`, is the least-invasive shape.
3. **Scoring** (`libs/fred-deepeval-cli`, `score_trace`) — accept `custom_metrics` and, for
   each, append a `GEval(name=…, criteria=…, evaluation_params=…, threshold=…, model=judge)`
   to the metric list. The existing measure/verdict/store loop handles the rest.
4. **Activity wiring** (`workers/activities.py`) — pass the campaign's `custom_metrics`
   into `score_trace`, next to `profile` and `judge`.

### 3.2 What does NOT change
- The output model `EvaluationMetricResult` — a GEval result fits it as-is.
- The verdict aggregation in `finalize_campaign` — a custom metric counts like any other.
- The `EvaluationTaskEvent` lifecycle from EVAL-SCHEDULING-BUS.

---

## 4. The cross-repo constraint — resolved

The metric definition lives in `fred-deepeval-cli`, which is published on PyPI. **But the
evaluator does not consume the PyPI build — it consumes the local source as an editable
install:**

```toml
fred-deepeval-cli = { path = "../../libs/fred-deepeval-cli", editable = true }
```

So editing `libs/fred-deepeval-cli/.../scorer.py` takes effect **immediately** at the next
worker start — no republish needed. The `>=0.1.2` floor in `pyproject.toml` is only a
lower bound; the resolved source is the local path.

The PyPI build matters only for *other* consumers of the package, if any exist outside
this repo. The package is authored and published by the same team, so propagating the
change to those consumers is a version bump (currently `0.1.3` → `0.1.4`) done at will —
not a blocker. **Bump the version when `score_trace`'s signature changes**, so external
consumers pin the new contract; the evaluator itself needs no bump to pick it up.

---

## 5. Non-goals
- ~~Selecting/deselecting the five built-in metrics per campaign~~ **Done, in the same
  change as this RFC's implementation** — see §9. The reason: shipping custom metrics
  without also letting the caller pick which built-ins run left analysts stuck with
  whatever `resolve_profile()` guessed (e.g. a general-purpose agent with
  document/tabular tools manually attached always fell back to `default` →
  `AnswerRelevancy` only, regardless of the tools actually in play).
- A reusable metric library / marketplace across campaigns. Here criteria are attached to
  one campaign at creation; sharing them is a later concern.
- Changing profile auto-detection **for structural checks** (SQL/RAG/workflow non-LLM
  checks in `build_structural_checks`) — `resolve_profile()` still runs automatically for
  those; only the DeepEval *metric* list stopped depending on it.

---

## 6. Risks
| Risk | Mitigation |
| --- | --- |
| A GEval call is an extra LLM round-trip per case per criterion — cost and latency | cap the number of custom metrics per campaign; document the cost |
| Vague criteria give noisy scores | require a non-empty `criteria`; surface GEval's `explanation` in results so a low score is legible |
| `fred-deepeval-cli` consumed from PyPI elsewhere | §4 — confirm before landing; bump the package version |
| Prompt injection via `criteria` into the judge | the criterion is authored by the campaign creator, already trusted to define the run; no new trust boundary, but note it |

---

## 7. Open questions
1. Where do criteria live long-term — only on the campaign, or a reusable per-team library?
2. Which `GEvalParam` values do we expose in the UI? All of DeepEval's, or a curated
   subset (`INPUT`, `ACTUAL_OUTPUT`, `EXPECTED_OUTPUT`, `RETRIEVAL_CONTEXT`, `TOOLS_CALLED`)?
3. Max number of custom metrics per campaign (cost bound)?
4. ~~Is `fred-deepeval-cli` published/consumed outside this repo (§4)?~~ **Resolved:**
   published on PyPI but consumed here as an editable local install — local edits are live;
   version-bump only propagates to external consumers. No blocker.

---

## 8. Acceptance criteria
- [x] `StartRunRequest` accepts `custom_metrics`; they are persisted on the run
  (`custom_metrics_json`) and readable by the worker.
- [x] `score_trace` scores each custom criterion via `GEval`, producing an
  `EvaluationMetricResult` indistinguishable in shape from a built-in metric.
- [x] A custom metric's score, verdict, and explanation appear in the run results and
  count in the run verdict.
- [ ] The `fred-deepeval-cli` version is bumped if its `score_trace` signature changes —
  not done in this change (`score_trace` gained a new optional `metrics` parameter;
  existing callers are unaffected, so treated as non-breaking). Revisit if that judgment
  turns out wrong for an external consumer.

---

## 9. Implementation notes (2026-07-21)

Landed together with manual built-in metric selection (§5). Current file names (see the
vocabulary note at the top):

- `runs/metrics_catalog.py` (**new**, `fred-evaluation-backend`) — the built-in metric id
  catalog (`answer_relevancy`, `faithfulness`, `contextual_relevancy`,
  `contextual_precision`, `contextual_recall`). Deliberately dependency-free: no
  `deepeval`, no `fred_deepeval_cli` import.
- `runs/schemas.py::CustomMetricSpecInput` (**new**) — API-side twin of
  `fred_deepeval_cli.core.models.CustomMetricSpec`, discovered to be necessary because
  **the API image never installs `deepeval`/`fred-deepeval-cli`**
  (`dockerfiles/Dockerfile-api`, `scoring` extra is worker-only). `CustomMetricSpec`'s
  `parameters` validator imports `deepeval.test_case.LLMTestCaseParams`, which would crash
  the API process. `CustomMetricSpecInput` validates shape only; the DeepEval-enum check
  stays worker-side, so a bad `parameters` name now surfaces as a per-case scoring error
  at run time instead of a validation error at run-creation time — an accepted trade-off
  of the API/worker boundary, not a bug.
- `runs/schemas.py::StartRunRequest.metrics: list[str]` (**new**, required, non-empty) —
  the manual built-in-metric selection from §5.
- `runs/models.py::EvaluationRunRow.metrics_json` (**new column**, migration
  `20260721_01_add_run_metrics_json.py`) — mirrors `custom_metrics_json`'s existing
  pattern (separate nullable `Text` column, not folded into `RunSnapshot`).
- `fred_deepeval_cli.core.scorer.score_trace(metrics=...)` (**new optional param**) —
  when given, replaces the profile cascade for the built-in metric list (custom metrics
  are unaffected either way); `None` (the default) preserves the old automatic cascade for
  the CLI standalone path (`evaluator.py::evaluate_case_sync`), which has no explicit
  selection to pass. `contextual_precision`/`contextual_recall` selected without
  `expected_output` produce verdict `"skipped"` instead of erroring.
- `resolve_profile()` / `build_structural_checks()` are untouched — still automatic, now
  used only for the non-LLM SQL/RAG/workflow checks (§5, third non-goal).
