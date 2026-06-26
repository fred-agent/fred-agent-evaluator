# RFC EVAL-DATASET — Dataset Domain: Capture, Curation & Evaluation Datasets

**Status:** draft
**Version:** v1 proposal
**Date:** 2026-06-25
**Authors:** Odelia Cohen; inputs from Thomas Delavallade, Laurence Guillon, Dimitri Tombroff
**Reviewers:** Evaluation backend owner, Frontend owner, IA direction (T. Delavallade)
**Track:** `EVAL-DATASET`
**Backlog:** [`docs/backlog/EVAL-DATASET-BACKLOG.md`](../backlog/EVAL-DATASET-BACKLOG.md)

---

## 1. Decision requested

Approve a precise model for the "dataset" domain that disambiguates three overloaded
meanings (raw capture, curated set, evaluation-ready dataset) into **two persisted models**
plus an explicit lifecycle, and a clean separation between the platform's storage schema and
the schema DeepEval consumes.

---

## 2. Problem

The word "dataset" is overloaded. Today it can mean three different things:

1. The **raw capture** of agent ↔ user conversations pulled from history (e.g. the last
   7 days for one agent), with no triage and no expected output.
2. A **curated set** of questions after triage (relevant questions kept).
3. A **ready-to-evaluate** artifact handed to a campaign, sometimes with expected output,
   sometimes without.

This ambiguity blocks a clean data model and a clean UI, and risks conflating the
platform's own storage schema with the schema DeepEval expects.

---

## 3. Terminology

Three concepts, **two persisted models**.

| Term | Model / state | Expected output? | Evaluable? |
| --- | --- | --- | --- |
| **Capture** | `QuestionSet` with `status = captured` | No | No |
| **Curated set** | `QuestionSet` with `status = curated` | Not necessarily | Minimal mode only |
| **Dataset** | `EvaluationDataset` (frozen, versioned) | Optional (`minimal`) or present (`complete`) | Yes |

A third schema, `LLMTestCase`, exists but is **owned by DeepEval** — it is neither a table
nor a UI component, only an ephemeral projection produced at scoring time.

---

## 4. Goals

- G1 — Disambiguate "dataset" into precise, named concepts.
- G2 — Provide a curation pipeline: import Q/A from history (agent + team + period), score
  questions on triage criteria (1–5), filter, and promote to a dataset.
- G3 — Support datasets **with or without** expected output (`minimal` / `complete`) and
  make the applicable metrics derivable from that.
- G4 — Keep platform storage (Postgres columns + JSON blobs) decoupled from DeepEval's
  `LLMTestCase`, with schema guaranteed declaratively by Pydantic (no hand-written
  validation).

## 5. Non-goals

- Re-implementing scoring math (DeepEval-owned).
- Expected-output *construction* workflows (feedback loop, auto-promotion) — covered by the
  parent evaluation platform RFC; only referenced here.
- A document/corpus versioning system (we reference Knowledge Flow, we don't own it).
- Retention policy mechanics (platform-level concern).

---

## 6. Design principles

### P1 — Two models, not three
*Capture* and *Curated set* are the **same object in two states** (a `QuestionSet`):
curation only adds triage scores and keep/drop decisions to the same collection of items.
*Dataset* is a **distinct model** (`EvaluationDataset`): it changes nature — immutable,
versioned, and the input contract to campaigns.

### P2 — Datasets are immutable and versioned
An `EvaluationDataset` never changes in place. Any evolution (adding expected output,
re-triage) produces a new version. The originating `QuestionSet` keeps living independently.

### P3 — Pydantic models are the schema and the guarantee
Nested/variable structures live in JSON columns; their shape is enforced declaratively at
the (de)serialization boundary (`model_validate` / `model_dump`). No hand-written
validation code. The same models feed the API and OpenAPI (single source of truth).

### P4 — Separate vocabularies, explicit adapter
Curation uses the *conversation* vocabulary (`question`/`answer`); datasets use the
*evaluation* vocabulary (`input`/`expected_output`); DeepEval owns `LLMTestCase`. The
worker translates `DatasetCase → LLMTestCase` at scoring time.

---

## 7. Data model

### 7.1 Model A — `QuestionSet` (capture + curation)

One model covers capture and curated set, distinguished by `status`.

```python
class QuestionSetStatus(str, Enum):
    captured = "captured"   # imported, not yet triaged
    scoring  = "scoring"    # triage running
    curated  = "curated"    # triage done, ready to promote

class QuestionTriageScore(BaseModel):
    # The 3 triage criteria, each scored 1..5
    is_relevant_question: int     # filters "thanks", "hi"…
    is_rag_question: int          # is it actually a RAG query?
    answerability: int            # can it be answered from the corpus?
    raw_llm: str | None           # raw triage-judge output

class QuestionCandidate(BaseModel):
    candidate_id: str
    question: str                 # message role=user (from history)
    answer: str | None            # associated message role=assistant
    source_session_id: str | None
    source_exchange_id: str | None
    captured_at: datetime
    triage: QuestionTriageScore | None = None   # None until scored
    kept: bool = False            # True when all 3 criteria >= keep_threshold

class QuestionSet(BaseModel):
    schema_version: Literal["1"] = "1"
    question_set_id: str
    team_id: str
    agent_id: str
    created_by: str
    status: QuestionSetStatus = QuestionSetStatus.captured
    # import filters ("Analytics"-style)
    period_from: datetime | None
    period_to: datetime | None
    extra_filters: dict[str, str] = {}    # user_id, session_id…
    keep_threshold: int = 4               # ">= 4/5" rule
    candidates: list[QuestionCandidate]
    created_at: datetime
    updated_at: datetime
```

Internal lifecycle: `captured` → (scoring) → `curated`. Promotion to `curated` erases
nothing: **all** candidates are kept (selected and rejected) with their scores, for
traceability.

### 7.2 Model B — `EvaluationDataset` (frozen, versioned)

A distinct model, immutable once created. This is what a campaign consumes.

```python
class DatasetCompleteness(str, Enum):
    minimal  = "minimal"    # input only (no expected_output) → reference-free metrics
    complete = "complete"   # input + expected_output → all metrics

class DatasetCase(BaseModel):
    external_id: str | None
    input: str
    expected_output: str | None = None
    tags: list[str] = []
    # provenance (curation traceability)
    source_candidate_id: str | None = None
    source_session_id: str | None = None

class EvaluationDataset(BaseModel):
    schema_version: Literal["1"] = "1"
    dataset_id: str
    name: str
    version: str                          # immutable; new curation = new version
    team_id: str
    created_by: str
    origin: Literal["capture", "upload", "manual"]
    source_question_set_id: str | None    # link to the originating QuestionSet
    completeness: DatasetCompleteness     # derived: minimal if any case lacks expected_output
    cases: list[DatasetCase]
    created_at: datetime
```

### 7.3 Why `DatasetCase` ≠ `QuestionCandidate`

| `QuestionCandidate` (curation) | `DatasetCase` (frozen dataset) |
| --- | --- |
| `question` / `answer` (raw) | `input` / `expected_output` (eval contract) |
| `triage` (triage scores /5) | no triage (already filtered) |
| `kept` (decision) | only exists if kept |
| mutable (scored, kept/dropped) | **immutable** (frozen in a version) |

`DatasetCase` follows the evaluation vocabulary (`input`, `expected_output`) — close to
DeepEval's `LLMTestCase` — whereas `QuestionCandidate` follows the conversation vocabulary
(`question`, `answer`) coming from history.

### 7.4 The third schema — `LLMTestCase` (DeepEval, not ours)

At scoring time the worker translates each `DatasetCase` + the agent's response into a
DeepEval `LLMTestCase` (schema imposed by the library, not modifiable):

```python
LLMTestCase(
    input: str,
    actual_output: str | None,            # response generated by the evaluated agent
    expected_output: str | None,          # from DatasetCase.expected_output
    retrieval_context: list[str] | None,  # from the agent's RAG trace
    context: list[str] | None,
    tools_called, expected_tools,
)
```

Three schemas, three roles:
- `QuestionSet` / `QuestionCandidate` — **curation** (conversation vocabulary)
- `EvaluationDataset` / `DatasetCase` — **evaluable storage** (eval vocabulary, versioned)
- `LLMTestCase` — **scoring input** (DeepEval-owned, ephemeral)

---

## 8. Persistence (DB schema vs JSON schema)

Following the existing evaluator pattern (`*_json` columns on `EvaluationCampaignRow`):

- **Typed SQL columns** for everything we filter / sort / join / index: `*_id`, `team_id`,
  `agent_id`, `status`, `version`, `completeness`, `created_at`.
- **A single JSON column** for nested / variable structures: `candidates`, `cases`,
  `triage`, `extra_filters`.
- **Pydantic models are the schema and the guarantee** (P3) — no hand-written validation.

Example mapping for `EvaluationDataset`:

| Field | Storage |
| --- | --- |
| `dataset_id`, `name`, `version`, `team_id`, `created_by`, `origin`, `completeness`, `created_at`, `source_question_set_id` | typed columns |
| `cases` (list of `DatasetCase`) | one JSON column |

---

## 9. Metric → required fields matrix

`completeness` determines which metrics are applicable, because each metric needs specific
fields. This enables pre-campaign validation (reject incompatible selections early).

| Metric | input | actual_output | retrieval_context | expected_output | Works on `minimal`? |
| --- | :---: | :---: | :---: | :---: | :---: |
| Answer Relevancy | ✓ | ✓ | | | ✅ |
| Faithfulness | | ✓ | ✓ | | ✅ |
| Contextual Relevancy | ✓ | | ✓ | | ✅ |
| Hallucination | | ✓ | (context) | | ✅ |
| Contextual Precision | ✓ | | ✓ | ✓ | ❌ (needs expected) |
| Contextual Recall | | | ✓ | ✓ | ❌ (needs expected) |
| Custom (G-Eval) | depends on declared params | | | | depends |

---

## 10. Lifecycle

```
        HISTORY (fred_core.history : ChatMessage)
              |
              |  import  ("Analytics"-style filters: agent, team, period)
              v
   +-----------------------------+
   | QuestionSet  status=captured |   <- Raw capture (Q/A, no triage, no expected)
   +-----------------------------+
              |  scoring (3 criteria /5)        [OPTIONAL step]
              v
   +-----------------------------+
   | QuestionSet  status=curated  |   <- Curated set (kept = True/False per candidate)
   +-----------------------------+
              |  promote (select kept + optional expected_output)
              v
   +-----------------------------+
   | EvaluationDataset  v1        |   <- Frozen, versioned dataset
   |   completeness = minimal     |       - minimal  : no expected_output
   |                 | complete   |       - complete : with expected_output
   +-----------------------------+
              |  selection at campaign creation
              v
   +-----------------------------+
   | Evaluation campaign          |
   |  run_case -> agent (prod)    |
   |   -> DatasetCase -> LLMTestCase |  <- translation at scoring
   |   -> DeepEval (metrics)      |
   +-----------------------------+
```

**Skippable steps (modular flow):**

- *Already have a dataset* → skip capture + triage, select the `EvaluationDataset` directly
  at campaign creation.
- *Capture already clean* → skip triage (`scoring`) and promote directly.
- *No expected output* → dataset is `minimal`; only reference-free metrics apply (Archie case).

**Invariants:**

- An `EvaluationDataset` is **immutable**; any change creates a **new version** (P2).
- A `QuestionSet` **keeps all candidates** (kept and dropped) with their scores.
- `completeness` is **derived** from the cases (minimal as soon as one case has no
  expected_output) and determines applicable metrics.

---

## 11. Alternatives considered

- **Three separate models** (capture, curated set, dataset). Rejected: capture and curated
  set are the same collection in different states; a third table adds redundancy and
  synchronization cost for no benefit (P1).
- **One model for everything** (a single "dataset" with flags). Rejected: conflates the
  mutable curation phase with the immutable, versioned evaluation artifact, which have
  different invariants and different vocabularies.

---

## 12. Impact on existing contracts

- Additive: new tables `question_set`, `evaluation_dataset`. No change to existing campaign
  tables beyond an optional `dataset_id` reference at campaign creation.
- Campaign creation accepts a `dataset_id` (referencing an `EvaluationDataset`) in addition
  to the current inline-cases path; both remain supported.
- The scoring worker gains a `DatasetCase → LLMTestCase` adapter; metric implementations are
  unchanged (DeepEval-owned).

---

## 13. Open questions

- Export/retrieval format for curated questions (CSV, JSON, both?) and the canonical field
  set (question, answer, session_id, agent_id, timestamp, …).
- Should the question import reuse the existing Analytics query layer rather than
  reimplementing the period/agent/team filtering?
- Exact definitions and thresholds of the 3 triage criteria (to be frozen with Laurence).
- Where retention of `QuestionSet` / `EvaluationDataset` is defined (platform-level
  retention primitive vs evaluator-local).
