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

- [ ] Pydantic models: `QuestionSet`, `QuestionCandidate`, `QuestionTriageScore`,
      `EvaluationDataset`, `DatasetCase`, enums (`QuestionSetStatus`, `DatasetCompleteness`)
- [ ] SQLAlchemy table `question_set` (typed columns + JSON column for `candidates`)
- [ ] SQLAlchemy table `evaluation_dataset` (typed columns + JSON column for `cases`)
- [ ] Alembic migration
- [ ] Unit tests: serialization, `completeness` derivation, versioning invariant

### Phase 2 — Capture (import from history)

- [ ] `POST /evaluation/v1/question-sets:import` (Analytics-style filters: agent, team, period)
- [ ] Wire import to `fred_core.history` (reuse the Analytics query layer)
- [ ] `GET /evaluation/v1/question-sets`, `GET /evaluation/v1/question-sets/{id}`

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
- Reuse the existing Analytics query layer vs reimplement period/agent/team filtering.
- Exact definitions and thresholds of the 3 triage criteria (to be frozen with Laurence).
- Where retention of `QuestionSet` / `EvaluationDataset` is defined.
