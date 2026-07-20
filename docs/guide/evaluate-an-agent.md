# Evaluate an agent — the full journey

**For:** the analyst on a Fred team. This document ties the five steps together; each one
links to its detail. The heart of the analyst's work is step 3.

---

## The five steps

### 1 & 2 — On the Fred side (prerequisites)

These two steps happen in Fred (`~/Fred/fred`), not in this repo:

1. **Ingest the corpus** into the team (Knowledge Flow).
2. **Have a ReAct agent** equipped with the search tool over that corpus.

Once both are in place, you have what you need: a **managed agent instance**
(`agent_instance_id`) and a team (`team_id`). **EVAL-04 (first release, 2026-07-16):
runs target a managed agent instance only** — a bare `runtime_id`/`agent_id`
pair is no longer an accepted target at creation (still readable on runs
created before this release).

### 3 — Write the dataset ← *your work*

Write the list of questions (± expected answers), then save it as an
**evaluation**: the immutable, versioned definition, reusable across future runs.
Dedicated guide: **[`write-a-dataset.md`](write-a-dataset.md)**.

```jsonc
POST /evaluation/v1/evaluations      // → 201, returns evaluation_id (+ version, completeness)
{
  "team_id": "<team>",
  "name": "ArxivAi — analyst set",
  "origin": "upload",
  "source_filename": "arxiv-ai-eval.json",
  "cases": [ /* your file, [{ "input": "...", "expected_output": "..." }, ...] */ ]
}
```

### 4 — Start a run

A run is one execution of that evaluation against a target. The server owns the
scoring profile, the judge and the concurrency/timeout defaults this release,
and freezes them into a `RunSnapshot`:

```jsonc
POST /evaluation/v1/evaluations/{evaluation_id}/runs   // → 202, returns run_id
{
  "team_id": "<team>",
  "target": { "kind": "managed_instance", "agent_instance_id": "<instance>" }
}
```

The worker then runs each case against the agent, captures the answer and the RAG trace,
and scores it. Each case is persisted independently. Re-running the same evaluation
creates a **new run** and never overwrites previous results — that is how you compare
two agent versions on the same questions.

### 5 — Read the results

- **Real-time progress:** `GET /runs/{run_id}/events` (SSE).
- **Verdict + aggregates:** `GET /runs/{run_id}`.
- **Per-case detail:** `GET /runs/{run_id}/cases` (score, verdict, produced answer,
  judge explanation).
- **All runs of an evaluation:** `GET /evaluations/{evaluation_id}/runs`.

---

## Pointers

- Full routes and statuses: [`../DEVELOPER_CONTRACT.md`](../DEVELOPER_CONTRACT.md).
- Worker → runtime → scoring flow: [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
- Data model (dataset, cases, versions): [`../rfc/EVAL-DATASET-RFC.md`](../rfc/EVAL-DATASET-RFC.md).
- Deploying the platform: [`../DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md).
