# RFC EVAL-CUSTOM-METRIC — User-defined evaluation criteria via GEval

**Status:** draft for discussion
**Author:** Odelia Cohen
**Reviewers:** Dimitri Tombroff, Evaluation backend owner
**Track:** `EVAL-CUSTOM-METRIC`
**Related:** `EVAL-DATASET-RFC.md` (campaign creation payload), `EVAL-SCHEDULING-BUS-RFC.md`
(campaign lifecycle), `libs/fred-deepeval-cli` (`score_trace`)

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
- Selecting/deselecting the five built-in metrics per campaign (that is configuration, not
  a custom metric — a separate, smaller change if wanted).
- A reusable metric library / marketplace across campaigns. Here criteria are attached to
  one campaign at creation; sharing them is a later concern.
- Changing profile auto-detection.

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
- `CreateEvaluationCampaignRequest` accepts `custom_metrics`; they are persisted on the
  campaign and readable by the worker.
- `score_trace` scores each custom criterion via `GEval`, producing an
  `EvaluationMetricResult` indistinguishable in shape from a built-in metric.
- A custom metric's score, verdict, and explanation appear in the campaign results and
  count in the campaign verdict.
- The `fred-deepeval-cli` version is bumped if its `score_trace` signature changes.
