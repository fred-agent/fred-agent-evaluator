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

**Decision (architecture, agreed with runtime owner):** the conversations live in
`session_history`, owned by fred-runtime — a different service. The evaluator does
NOT read that DB directly. A new read endpoint is added in **fred-runtime**, kept as
an **isolated, decoupled component** so its hosting can be decided later:
fred-agents (client-side code, has Keycloak) **vs** control-plane (core infra code) —
runtime owner leans towards control-plane being the better long-term home. The
evaluator calls it over HTTP in M2M (same channel as `evaluate_url`). Tracked in the
fred repo (see Execution below).

**Runtime endpoint contract (to build in fred):**

- Filters **team_id + agent_instance_id + period are mandatory**, with a
  **server-capped period** (e.g. ≤ 90 days) — never "dump everything".
- **Cursor-based pagination + async streaming (mandatory)** — a large history must
  NOT be loaded in RAM nor returned in one huge payload; stream page by page via an
  explicit cursor. Hard limit per page (default 100, max ~1000).
- Only `user`/`assistant` roles; **field projection** (`role`, `content`,
  `session_id`, `exchange_id`, `timestamp`, `user_id`).
- **Authorization scoped by team** (cannot read a team's history without access) — RGPD.
- The endpoint **bounds volume only**; it does NOT judge relevance (that is the
  Phase 3 triage judge, evaluator-side).
- **Isolation requirement:** the history-read logic must be a self-contained component
  in fred-runtime, decoupled from its HTTP host, so it can be mounted on fred-agents
  or control-plane without rewrite (placement to be finalized).

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
- Endpoint **hosting**: fred-agents (client code) vs control-plane (core infra) —
  deferred; component kept isolated so it can move. Runtime owner leans control-plane.
