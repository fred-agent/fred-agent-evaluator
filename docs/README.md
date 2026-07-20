# Documentation — fred-agent-evaluator

Single entry point. Pick your role, follow the link.

`fred-agent-evaluator` evaluates a Fred agent **under real conditions**: it asks the
agent a set of questions, captures its answers (and its RAG trace), then **scores** the
quality with metrics (faithfulness, relevancy, hallucination…).

---

## Who are you?

| I am…                                                          | Start here                                                                    |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **An analyst** on a Fred team, I want to evaluate my agent     | [`guide/evaluate-an-agent.md`](guide/evaluate-an-agent.md) *(the full journey)* |
| **An analyst**, I want to write my question/answer set         | **→ [`guide/write-a-dataset.md`](guide/write-a-dataset.md)** *(current focus — [FR](guide/write-a-dataset.fr.md))* |
| **An operator** deploying the platform                         | [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md)                                   |
| **A developer** touching the API or the worker                 | [`DEVELOPER_CONTRACT.md`](DEVELOPER_CONTRACT.md) then [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| **An architect** reviewing or proposing a change               | [`rfc/`](rfc/) then [`ARCHITECTURE.md`](ARCHITECTURE.md)                       |
| **An AI assistant** (Claude Code)                              | [`../CLAUDE.md`](../CLAUDE.md) — mandatory read order                          |

---

## The analyst journey (the simple story)

You are a member of a Fred team. A corpus is already ingested into the team and a ReAct
agent knows how to search it. You want to measure its quality. Five steps:

| # | Step                                                   | Where it happens              | Doc                                             |
| - | ------------------------------------------------------ | ----------------------------- | ----------------------------------------------- |
| 1 | Ingest the corpus into the team                        | Fred (Knowledge Flow)         | *Fred doc — outside this repo*                  |
| 2 | Have a ReAct agent equipped with the search tool       | Fred (Agent Studio)           | *Fred doc — outside this repo*                  |
| 3 | **Write the JSON dataset** (questions ± expected answers) | **here**                    | **[`guide/write-a-dataset.md`](guide/write-a-dataset.md)** ← *focus* |
| 4 | Start a run targeting the agent                        | here (API `POST /evaluations/{id}/runs`) | [`guide/evaluate-an-agent.md`](guide/evaluate-an-agent.md) |
| 5 | Read the verdict and per-case scores                   | here (API + Fred frontend)    | [`guide/evaluate-an-agent.md`](guide/evaluate-an-agent.md) |

> Steps 1 and 2 belong to Fred itself (`~/Fred/fred`), not to this repo. This repo starts
> at step 3: **your dataset is the starting point of every evaluation.**

---

## Folder map

| Folder / file                              | Contents                                                      | Lifecycle             |
| ------------------------------------------ | ------------------------------------------------------------- | --------------------- |
| [`guide/`](guide/)                         | Task-oriented guides (analyst, operator)                      | Living                |
| [`ARCHITECTURE.md`](ARCHITECTURE.md)       | Components, end-to-end flow, dependencies                     | Stable — via RFC      |
| [`DEVELOPER_CONTRACT.md`](DEVELOPER_CONTRACT.md) | API contract, invariants, dataset format                | Stable — via RFC      |
| [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) | Docker Compose, Helm, prod config                           | Living                |
| [`rfc/`](rfc/)                             | Technical proposals (e.g. `EVAL-DATASET-RFC.md`)              | open → decided        |
| [`backlog/`](backlog/)                     | Tracking log, never rewritten                                 | Append-only           |

**Cross-reference rule:** only this `README.md` points to everything. Other documents
reference only their own folder or the stable contracts.

> **Language:** all documentation is written in **English**. The analyst dataset guide is
> also available in French as a convenience: [`guide/write-a-dataset.fr.md`](guide/write-a-dataset.fr.md).
