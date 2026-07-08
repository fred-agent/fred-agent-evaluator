# RFC EVAL-TRIAGE — Dataset triage: turning captured conversations into an evaluation dataset

**Status:** draft for discussion (architecture exploration — no implementation committed)
**Author:** Odelia Cohen
**Reviewers:** Dimitri Tombroff (runtime/control-plane), Evaluation backend owner, Frontend owner, IA direction (T. Delavallade)
**Track:** `EVAL-TRIAGE`
**Related:** `EVAL-DATASET-RFC.md` (capture + curation model), `EVAL-AUTH-RFC.md` (worker authorization)

---

## 1. Purpose

Capture pulls raw Q/A from conversation history into a `QuestionSet` (Phase 2, done).
**Triage** is the next phase: turn that raw set — potentially **thousands** of
candidates — into a **curated** selection worth evaluating, then promote it to a
frozen `EvaluationDataset`.

This RFC does **not** commit an implementation. It maps **all the dimensions, risks
and open questions** so we choose deliberately, because (per Dimitri) the naive
"filter 1000 → keep 50" mental model breaks when triage still leaves 1000.

---

## 2. The one constraint that shapes everything: scale

The volume of captured candidates (`N`) is **unbounded and often large** (e.g. 7 days
of one agent = hundreds to thousands of exchanges). Two regimes:

| Regime | Example | Consequence |
| --- | --- | --- |
| Triage reduces a lot | 1000 → 50 | a plain list works |
| Triage reduces little | 1000 → 1000 | a plain list is **unusable** |

The second regime is real (a busy agent gets 1000 legitimate RAG questions). So the
surface must be a **dashboard** (OpenSearch/Grafana style): server-side pagination,
faceted filtering, aggregate counts, sorting, search, and **bulk actions** — never a
client-side scrollable list. **Everything below is designed for large `N`.**

**Corollary:** deterministic triage does **not delete** candidates — it **labels**
them. Labels become the dashboard facets. The human curates **by batch**, not item by
item.

---

## 3. What data do we actually have at triage time?

Only two texts per candidate, from conversation history:
- the **question** (user message),
- the **production answer** (what the agent said then — a signal, not ground truth).

We do **not** have: the execution trace (`tools_called`, `retrieval_context`), nor an
`expected_output`. Triage is therefore **question selection**, not scoring against a
reference. `expected_output` is added later (optional, for reference-based metrics).

---

## 4. Dimensions to design

### 4.1 The triage pipeline (a funnel, cost-ordered)
1. **Deterministic (0 LLM)** — regex/heuristics on question + prod answer: empty,
   too-short, greeting/politeness-only, exact duplicate, "prod said I don't know".
2. **Embeddings (cheap, no generation)** — semantic **dedup** (keep a representative),
   and **answerability by retrieval** (does the team corpus have close chunks?).
3. **LLM (expensive, last)** — a **small** model, **batched** (N questions per call),
   only on the ambiguous residue; scores the 3 RFC criteria (relevance, is-RAG,
   answerability) 1–5.

**Principle:** the LLM sees only the residue, in batch, with a small model. Most
labeling is free/cheap. v1 can be **deterministic-only**.

### 4.2 Data model & labeling
- `QuestionCandidate.kept: bool`, plus a **`reject_reason`** (facet) and optional
  `triage` scores (None until an LLM stage runs).
- **Nothing is deleted**: kept and rejected both persist, with reason — for
  traceability and to let the human override.
- **Provenance**: `source_session_id`, `source_exchange_id`, `captured_at`.

### 4.3 Storage & query engine (the scale question)
Postgres alone (the current store) can page/filter, but faceted aggregation over
thousands of rows + free-text search + semantic dedup is what **OpenSearch** is built
for. Decision to make: **Postgres vs OpenSearch (or hybrid)** for the candidate store.
This is likely the single biggest architectural choice.

### 4.4 API surface (must be built for volume from day one)
- `GET /question-sets/{id}/candidates?kept=&reject_reason=&q=&sort=&page=&size=`
  (server-side pagination + filtering + search).
- `GET /question-sets/{id}/facets` → aggregate counts per reason / kept / etc.
  (the dashboard panels).
- `PATCH /question-sets/{id}/candidates:bulk` → keep/drop over a **filter**, not a list
  of IDs (idempotent, bounded).
- `POST /question-sets/{id}/triage` → (re)run a triage stage (async, see 4.7).

### 4.5 Human-in-the-loop curation
- **Override** any automated decision (keep a rejected, drop a kept).
- **Bulk** curation over a filtered set ("drop all duplicates", "keep all non-greeting").
- Audit who changed what.

### 4.6 Answerability (and its hidden auth cost)
Answerability-by-retrieval needs **corpus access**. If computed server-side under a
service identity, it hits the **same knowledge-flow authorization** we just extended
for `service_agent` (EVAL-AUTH). If computed under the user's JWT (capture is sync),
it's simpler. **Decision:** who runs the answerability probe, and under which identity?

### 4.7 Sync vs async, progress, resumability
Triaging thousands of candidates (esp. embeddings/LLM) is **long** → must be an **async
job** (worker/task) with **status, progress, partial results, retry, resumability**.
Deterministic-only triage may be fast enough to be sync for small N, but design async.

### 4.8 Versioning & promotion
- Re-triage produces a **new version** of the curation; the originating `QuestionSet`
  keeps living.
- Promotion: `curated QuestionSet → EvaluationDataset` (frozen, versioned, immutable).
  `completeness` = minimal (input only) or complete (with expected_output).

### 4.9 Privacy / RGPD (conversations are personal data)
Captured conversations may contain **PII**. Questions to answer: retention of
candidates? anonymization/redaction before storage? who may view captured
conversations (team-scoped)? right-to-erasure propagation to QuestionSets/Datasets?
This is a **first-class** concern, not an afterthought.

### 4.10 Authorization & scoping
Triage is **team-scoped**. Who can capture, triage, curate, promote? Personal vs team
conversations. Reuse the team-permission model (manager/owner for management actions,
member for read).

### 4.11 Cost & observability
- Cost: bound LLM usage (funnel + batch + small model + caps + on-demand).
- Observability: metrics per stage (candidates in/out, reasons histogram, throughput,
  LLM tokens) — themselves a mini-dashboard.

### 4.12 Extensibility
Triage **stages/rules** should be pluggable (add a rule without a schema change), and
scoring **provider-agnostic** (reuse the judge factory).

---

## 5. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| **Volume explosion** (triage → still 1000s) | UI unusable, human overwhelmed | dashboard: server-side paging/facets/**bulk actions**; labels not deletion |
| **Cost explosion** (LLM per candidate) | expensive in prod | funnel + batch + small model + caps + on-demand; v1 no LLM |
| **Privacy / RGPD** (PII in conversations) | compliance breach | retention policy, anonymization, team scoping, erasure propagation |
| **Non-reproducible triage** (LLM drift) | dataset changes run-to-run | deterministic-first; version each triage; record the stage/model used |
| **Over-filtering** (drop good questions) | dataset misses real cases | keep rejected + reason + human override; conservative thresholds |
| **Under-filtering** (keep noise) | dataset diluted | facets + bulk drop; dedup |
| **Near-duplicate bloat** | redundant, skewed metrics | semantic dedup keep-representative |
| **Cross-team leak** | data exposure | scope every query to `team_id` |
| **Answerability needs corpus auth** | hidden auth complexity | decide identity (user JWT vs service_agent); reuse EVAL-AUTH |
| **Client-side scale** (load all rows) | browser crawl | never; server-side only |
| **Long triage jobs fail midway** | lost work | async job, resumable, partial persistence |

---

## 6. The good questions to answer before building

1. **Expected `N`?** tens / hundreds / thousands / tens-of-thousands — sets the storage
   and UI choices.
2. **Candidate store:** Postgres, **OpenSearch**, or hybrid? (facets + search + dedup at
   scale).
3. **v1 scope:** deterministic-only labeling + dashboard, or LLM from the start?
4. **Answerability:** compute it at all in v1? under which identity (user vs service)?
5. **Sync vs async** and progress model for large `N`.
6. **Bulk-action semantics:** apply to a *filter* (server-evaluated) vs a list of IDs?
7. **RGPD:** retention, anonymization, erasure — required at v1 or phased?
8. **Who** captures / triages / curates / promotes (permissions)?
9. **Dedup:** exact only (v1) or semantic (embeddings)?
10. **Promotion:** when does a curated set become a frozen dataset; versioning rules?
11. **Reject reasons taxonomy** — fixed enum or extensible?
12. **Idempotency / re-capture:** incremental capture + re-triage, or always full?

---

## 7. Alternatives considered (high level)

- **Naive list UI** — rejected: breaks at scale (Dimitri's warning).
- **LLM-scores-everything from v1** — rejected as default: cost + non-reproducibility;
  keep LLM as an optional late funnel stage.
- **Delete rejected candidates** — rejected: loses traceability and blocks human
  override; we **label**, never delete.
- **Client-side filtering** — rejected: does not scale; server-side only.

---

## 8. Proposed phasing (for discussion)

- **v1 — Deterministic labeling + dashboard skeleton.** Regex/heuristic labels +
  `reject_reason`; server-side paginated/filtered API + facets + bulk keep/drop;
  human override. No LLM, no embeddings. Proves the scale-safe surface.
- **v2 — Embeddings.** Semantic dedup + answerability-by-retrieval (decide identity).
- **v3 — Optional LLM stage.** Small model, batched, on the residue only; 1–5 scores.
- **Cross-cutting — RGPD & versioning** wired from v1 (retention/erasure hooks;
  triage versioning; promotion to frozen dataset).

---

## 9. Decision requested

Agree on: (a) the **scale-first** framing (dashboard, labels-not-deletion, server-side
everything), (b) the **candidate store** (Postgres vs OpenSearch), (c) the **v1 scope**
(deterministic + dashboard), and (d) the **RGPD** posture. The answers to §6 drive the
implementation RFC that follows.
