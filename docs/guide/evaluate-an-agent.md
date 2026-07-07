# Evaluate an agent — the full journey

**For:** the analyst on a Fred team. This document ties the five steps together; each one
links to its detail. The heart of the analyst's work is step 3.

---

## The five steps

### 1 & 2 — On the Fred side (prerequisites)

These two steps happen in Fred (`~/Fred/fred`), not in this repo:

1. **Ingest the corpus** into the team (Knowledge Flow).
2. **Have a ReAct agent** equipped with the search tool over that corpus.

Once both are in place, you have what you need: a `runtime_id` and an `agent_id` (the
target agent), and a team (`team_id`).

### 3 — Write the dataset ← *your work*

Write the list of questions (± expected answers). This is the only artifact you author by
hand. Dedicated guide: **[`write-a-dataset.md`](write-a-dataset.md)**.

### 4 — Create the campaign

Send the dataset together with the target and the judge:

```jsonc
POST /evaluation/v1/campaigns        // → 202, returns campaign_id + run_id
{
  "name": "ArxivAi — ReAct agent v1",
  "team_id": "<team>",
  "target": { "kind": "runtime_agent", "runtime_id": "<runtime>", "agent_id": "<agent>" },
  "profile": "auto",
  "judge_profile_id": "<judge>",
  "dataset": { "name": "arxiv-ai-eval", "version": "v1", "cases": [ /* your file */ ] }
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
