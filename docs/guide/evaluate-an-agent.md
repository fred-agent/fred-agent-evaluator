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
campaigns target a managed agent instance only** — a bare `runtime_id`/`agent_id`
pair is no longer an accepted campaign-creation target (still readable on
campaigns created before this release).

### 3 — Write the dataset ← *your work*

Write the list of questions (± expected answers), then save it as a
first-class, immutable dataset — it will be reusable across future campaigns.
Dedicated guide: **[`write-a-dataset.md`](write-a-dataset.md)**.

```jsonc
POST /evaluation/v1/datasets         // → 201, returns dataset_id (+ server-assigned name/version)
{
  "team_id": "<team>",
  "origin": "upload",
  "source_filename": "arxiv-ai-eval.json",
  "cases": [ /* your file, [{ "input": "...", "expected_output": "..." }, ...] */ ]
}
```

### 4 — Create the campaign

Reference the saved dataset by id — the server owns the campaign name, the
scoring profile, the judge, and the concurrency/timeout defaults this release:

```jsonc
POST /evaluation/v1/campaigns        // → 202, returns campaign_id + run_id
{
  "team_id": "<team>",
  "target": { "kind": "managed_instance", "agent_instance_id": "<instance>" },
  "dataset_id": "<dataset_id from step 3>"
}
```

The worker then runs each case against the agent, captures the answer and the RAG trace,
and scores it. Each case is persisted independently.

### 5 — Read the results

- **Real-time progress:** `GET /campaigns/{id}/events` (SSE).
- **Verdict + aggregates:** `GET /campaigns/{id}`.
- **Per-case detail:** `GET /campaigns/{id}/cases` (score, verdict, produced answer,
  judge explanation).

---

## Pointers

- Full routes and statuses: [`../DEVELOPER_CONTRACT.md`](../DEVELOPER_CONTRACT.md).
- Worker → runtime → scoring flow: [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
- Data model (dataset, cases, versions): [`../rfc/EVAL-DATASET-RFC.md`](../rfc/EVAL-DATASET-RFC.md).
- Deploying the platform: [`../DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md).
