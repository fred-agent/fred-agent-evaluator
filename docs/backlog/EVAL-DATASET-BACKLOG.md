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
  `session_history`, the write path (agents persist conversations), and the agent HTTP
  routes in its `app/` layer (e.g. `/agents/evaluate`). A library *defines* routes; it
  does not run a server. Depends on fred-core.
- **fred-agents** (app): the running service that uses fred-runtime + fred-core and owns
  the actual populated database. Depends on both.

The read path is split in two layers:

1. **Read component (logic)** — a `HistoryCaptureReader` class in **fred-core**, next to
   `SessionHistoryRow` / `PostgresHistoryStore`. Placed in fred-core (the lowest, most
   shared layer) for two reasons: (a) all history code already lives there → consistent;
   (b) fred-core is imported by *both* fred-agents and control-plane, so the endpoint can
   be hosted by either without coupling it to fred-runtime (control-plane does NOT depend
   on fred-runtime). **DONE** (fred repo, branch `1874-...`).
2. **HTTP endpoint (route)** — a thin route that just calls the fred-core reader.
   **Defined in fred-runtime's `app/` layer** (next to the existing `/agents/evaluate`
   and `/sessions/{id}/messages` routes) and **exposed/run by the fred-agents app**
   (which starts the server, owns the populated `session_history` DB and has Keycloak).
   This is the same define-in-runtime / run-in-fred-agents pattern as the other agent
   routes. The route is deliberately a small, removable adapter (~15 lines: auth check +
   call `fetch_page` + return). It is small **because all logic lives in the fred-core
   reader** — had the SQL/cursor/capping/projection lived in the route instead, it would
   be large, not reusable (control-plane would copy it), hard to test (needs a running
   server), and hard to move. Keeping the route thin gives: reusable logic, unit-testable
   without HTTP, and a movable endpoint. If it later moves to control-plane, control-plane
   defines its own thin route reusing the same fred-core reader — only the route is
   rewritten, never the logic. The evaluator calls
   it over HTTP in M2M (same
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

### Phase 4 — Dataset (EVAL-04: direct creation shipped; promotion pipeline still open)

- [ ] `POST /evaluation/v1/question-sets/{id}:promote` → `EvaluationDataset`
- [ ] Derived `completeness` computation + immutable versioning (via the promotion pipeline)
- [x] `POST /evaluation/v1/datasets` — direct creation, `origin: upload | manual`, no
      question-set promotion; server derives `name` (upload: source filename basename;
      manual: `"Manual dataset — <timestamp>"`) and `version` (fixed `"v1"`, no versioning
      UI yet). Shipped under `EVAL-04` (2026-07-16), see RFC §12 amendment.
- [x] `GET /evaluation/v1/datasets?team_id=...` — list, team-scoped. Shipped under
      `EVAL-04`.
- [ ] `GET /datasets/{id}`, `/datasets/{id}/versions` — not needed by the first-release UI
      (list response already carries selection-sufficient metadata); deferred to a future
      standalone dataset-management UI.
- [ ] Manual upload path via the capture/curation pipeline (`origin=upload` from
      `:promote`) — direct `POST /datasets` above covers `origin=upload`/`manual` without
      going through `QuestionSet`; this item is about the promotion-pipeline variant,
      still open.

### Phase 5 — Campaign / scoring integration

- [x] Campaign creation accepts `dataset_id` — shipped under `EVAL-04` (2026-07-16); the
      old inline `dataset`/`cases` request path was removed, not kept in parallel (see RFC
      §12 amendment).
- [ ] ~~`DatasetCase → LLMTestCase` adapter in the scoring worker~~ — **superseded**: the
      worker already scores `EvaluationCaseRow.input`/`expected_output` (unchanged shape);
      campaign creation now copies `EvaluationDataset.cases` into those rows instead of
      inline request cases, so no new adapter was needed.
- [ ] Pre-campaign validation via the metric → required-fields matrix
      (reject `minimal` dataset + reference-based metric) — moot in this release: no
      custom metrics or metric selection exist in the `EVAL-04` request contract.

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
- Endpoint **hosting**: **recommended = route defined in fred-runtime `app/`, run by
  fred-agents** (owns the populated DB, no extra hop, has Keycloak). Alternative =
  control-plane (does not own the conversation data → coupling or proxy). Deferred;
  the reader stays isolated in fred-core so the route can move without rewrite.
