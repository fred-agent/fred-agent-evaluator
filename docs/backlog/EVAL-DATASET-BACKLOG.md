# Dataset Domain — Implementation Backlog

**RFC**: [`docs/rfc/EVAL-DATASET-RFC.md`](../rfc/EVAL-DATASET-RFC.md)

**Status**: Not started — design drafted, awaiting confirmation

**Why this track exists**: The evaluator currently consumes ad-hoc inline cases, and the
word "dataset" is overloaded (raw capture, curated set, evaluation-ready artifact). This
track turns that into a first-class dataset domain: capture conversations from history,
curate them through triage, and freeze versioned datasets that campaigns consume — with a
clean separation between platform storage and DeepEval's input schema.

---

## 0 Overview

### 0.1 Goal

Introduce a first-class dataset domain for the evaluator that:

- captures agent ↔ user conversations from history with Analytics-style filters
- curates them through a triage pipeline (3 criteria, 1–5) into a kept selection
- freezes immutable, versioned `EvaluationDataset` artifacts consumed by campaigns
- supports datasets with or without expected output (`minimal` / `complete`)
- keeps platform storage decoupled from DeepEval's `LLMTestCase`

### 0.2 Why this matters

Without a dataset domain, evaluation inputs are ad hoc and non-reproducible: there is no
clean way to build a curated test set from real traffic, no versioning, and no explicit
notion of which metrics a dataset can support. The Archie/Bid&Capture use case (evaluate
on captured conversations without expected output) is not first-class today.

### 0.3 Core decision

Two persisted models, not three (RFC §6 P1):

1. `QuestionSet` — capture + curation, mutable, `status: captured → scoring → curated`
2. `EvaluationDataset` — frozen, versioned, the campaign input contract

`LLMTestCase` stays DeepEval-owned (ephemeral projection at scoring time).

---

## 1 Design rules

### 1.1 Two models, not three
Capture and curated set are the same `QuestionSet` in two states; the dataset is a distinct,
immutable, versioned artifact.

### 1.2 Datasets are immutable and versioned
Any change (expected output added, re-triage) produces a new dataset version.

### 1.3 Pydantic owns the JSON schema
Nested structures (`candidates`, `cases`) live in JSON columns; shape is guaranteed
declaratively by Pydantic — no hand-written validation. Queryable scalars stay typed columns.

### 1.4 Separate vocabularies, explicit adapter
Conversation (`question`/`answer`) → evaluation (`input`/`expected_output`) → DeepEval
(`LLMTestCase`). The worker owns the `DatasetCase → LLMTestCase` adapter.

---

## 2 Current implementation status

- Campaigns currently accept inline cases only; no `QuestionSet` / `EvaluationDataset`.
- Scoring already adapts a trace into DeepEval (`EvalTrace → LLMTestCase`) in
  `fred-deepeval-cli`; the dataset adapter will reuse this path.
- History store (`fred_core.history`) and the Analytics query layer already exist and will
  back the capture step.

---

## 3 Implementation plan

### Phase 1 — Data model & persistence

- [x] Pydantic models: `QuestionSet`, `QuestionCandidate`, `QuestionTriageScore`,
      `EvaluationDataset`, `DatasetCase`, enums (`QuestionSetStatus`, `DatasetCompleteness`)
- [x] SQLAlchemy table `question_set` (typed columns + JSON column for `candidates`)
- [x] SQLAlchemy table `evaluation_dataset` (typed columns + JSON column for `cases`)
- [x] Alembic migration
- [x] Unit tests: serialization, `completeness` derivation, versioning invariant

### Phase 2 — Capture (import from history)

**Decision (architecture, agreed with runtime owner):** the conversations live in the
`session_history` table. The evaluator is a separate service and must NOT read that
table directly → it goes through a dedicated read path in the fred repo.

_Package layering (to remove the recurring fred-core vs fred-runtime confusion):_

- **fred-core** (library): the shared toolbox — defines `SessionHistoryRow` (the table)
  and `PostgresHistoryStore`. **All history code lives here.** Imported by everyone.
- **fred-runtime** (library): the agent engine — owns the migration that creates
  `session_history` and the write path (agents persist conversations). Depends on fred-core.
- **fred-agents** (app): the running service that uses fred-runtime + fred-core and owns
  the actual populated database. Depends on both.

The read path is split in two layers:

1. **Read component (logic)** — a `HistoryCaptureReader` class in **fred-core**, next to
   `SessionHistoryRow` / `PostgresHistoryStore`. Placed in fred-core (the lowest, most
   shared layer) for two reasons: (a) all history code already lives there → consistent;
   (b) fred-core is imported by *both* fred-agents and control-plane, so the endpoint can
   be hosted by either without coupling it to fred-runtime (control-plane does NOT depend
   on fred-runtime). **DONE** (fred repo, branch `1874-...`).
2. **HTTP endpoint (route)** — in the host **app** that owns the populated DB + auth.
   **Recommended host: fred-agents** — it owns the `session_history` DB (direct access,
   no extra hop) and already has Keycloak. control-plane would have to read another
   service's table (coupling) or proxy to fred-agents (extra hop), since it does not own
   the conversation data. Logic stays in fred-core, so the endpoint can move to
   control-plane later without rewrite. The evaluator calls it over HTTP in M2M (same
   channel as `evaluate_url`). **TODO** (fred repo, #1874).

**`HistoryCaptureReader` contract (fred-core, done):**

- Filters **team_id + agent_instance_id + period mandatory**, **period capped**
  (≤ 90 days) — never "dump everything".
- **Cursor-based pagination** + hard limit (default 100, max 1000): each call reads
  at most one page → a large history is never loaded in RAM nor returned whole.
  (HTTP-level continuous streaming, if wanted, wraps this at the endpoint layer.)
- Only `user`/`assistant` roles; **field projection** (`role`, `content`,
  `session_id`, `exchange_id`, `timestamp`, `user_id`).
- Returns `CapturePage { messages, next_cursor }`.
- **Bounds volume only**; does NOT judge relevance (that is Phase 3, evaluator-side).
- **Authorization scoped by team** is the endpoint's responsibility (not the reader).

**Evaluator side (this repo):**

- [ ] `execution/history_client.py` — HTTP client calling the runtime endpoint (M2M)
- [ ] `POST /evaluation/v1/question-sets:import` (filters: `team_id`,
      `agent_instance_id`, `period_from`, `period_to`, optional `user_id`/`session_id`)
- [ ] Map history messages → `QuestionCandidate`, pairing user→assistant via `exchange_id`
- [ ] `datasets/store.py` + `datasets/service.py` + `datasets/api.py` (mirror `campaigns/`)
- [ ] `GET /evaluation/v1/question-sets`, `GET /evaluation/v1/question-sets/{id}`
- [ ] Tests + `make code-quality`

**Blocking dependency:** the runtime endpoint must exist (and its response shape be
frozen) before the evaluator's `history_client` can be finalized.

### Phase 3 — Curation (triage)

- [ ] `POST /evaluation/v1/question-sets/{id}:score` (3-criteria /5 triage judge)
- [ ] `kept` logic (threshold >= 4/5) and `captured → scoring → curated` transition

### Phase 4 — Dataset

- [ ] `POST /evaluation/v1/question-sets/{id}:promote` → `EvaluationDataset`
- [ ] Derived `completeness` computation + immutable versioning
- [ ] `GET /datasets`, `/datasets/{id}`, `/datasets/{id}/versions`
- [ ] Manual upload path (`origin=upload`)

### Phase 5 — Campaign / scoring integration

- [ ] Campaign creation accepts `dataset_id`
- [ ] `DatasetCase → LLMTestCase` adapter in the scoring worker
- [ ] Pre-campaign validation via the metric → required-fields matrix
      (reject `minimal` dataset + reference-based metric)

### Phase 6 — Frontend

- [ ] "Datasets" tab (list + creation)
- [ ] Capture screen (Analytics-style filters)
- [ ] Triage screen (3-criteria /5 scores, keep/drop)
- [ ] Dataset selector at campaign creation

### Phase 7 — Close-out

- [ ] `make code-quality` + `make test`
- [ ] Update `ARCHITECTURE.md` and the RFC status (draft → confirmed)

---

## 4 Open questions

- Export/retrieval format for curated questions (CSV, JSON, both?) and canonical field set.
- ~~Reuse the existing Analytics query layer~~ → **resolved**: no reusable conversation
  query exists; a dedicated runtime endpoint (fred-agents) is added instead (see Phase 2).
- Exact definitions and thresholds of the 3 triage criteria (to be frozen with Laurence).
- Where retention of `QuestionSet` / `EvaluationDataset` is defined.
- Runtime endpoint bounds to confirm with runtime owner: max period (≤ 90 d?) and
  hard page limit (~1000/call?).
- Endpoint **hosting**: **fred-agents (recommended** — owns the populated DB, no extra
  hop, has Keycloak) vs control-plane (does not own the conversation data → coupling or
  proxy). Deferred; component kept isolated in fred-core so it can move without rewrite.
