# Running a Local RAG Evaluation

## Objective

This guide explains how to run a local evaluation of `fred.github.rag_expert` using `fred-deepeval-cli`.

It covers:
- the role of the bearer token;
- the `SEARCH_POLICY=semantic` configuration;
- starting the required local services;
- the `make score` command;
- running a full campaign with `make rag-scenarios`;
- parallelising scenarios with `USE_TEMPORAL=1`.

---

## Prerequisites

The following services must be running locally before any evaluation:

- **`fred-agents`** — the agent runtime
- **Knowledge Flow** — the document search engine

---

## Why You Need to Start Knowledge Flow

`fred.github.rag_expert` can invoke the `knowledge_search` tool.

This tool does not perform the document search itself — it delegates to **Knowledge Flow**, which runs the actual search against the indexed corpus.

Without Knowledge Flow running:
- the agent may attempt a retrieval;
- but no document context will be returned;
- or a connection error will appear.

**Example error:**

```text
All connection attempts failed
```

---

## Why a Bearer Token Is Required

In some RAG scenarios, `knowledge_search` requires an **authenticated user context** to perform the search.

Without a valid bearer token, the following error may appear:

```text
Agent runtime_context has no access_token and refresh failed.
```

---

## Retrieving the Bearer Token

1. Start the application front end and open it in your browser.
2. Open the developer tools: **Inspect → Console**.
3. Run one of the following commands depending on your context:

```js
localStorage.getItem("keycloak_token")
```

or:

```js
localStorage.getItem("dev_admin_token")
```

4. Export the retrieved token in your shell:

```bash
export FRED_ACCESS_TOKEN="<token>"
```

---

## Why Use `SEARCH_POLICY=semantic`

Locally with **ChromaDB**, the default search policy may be set to `hybrid`, which is not always suited to a local setup.

For local RAG evaluations, semantic search is explicitly enforced:

```
SEARCH_POLICY=semantic
```

---

## `make score` Command

Fetches the trace, resolves the evaluation preset from `agent_tags`, computes structural checks, and runs DeepEval metrics:

```bash
make score \
  BASE_URL=http://127.0.0.1:8000/fred/agents/v2 \
  AGENT_ID=fred.github.rag_expert \
  INPUT='What are the three RAG evaluation metrics mentioned in the documents?' \
  SESSION_ID=rag-score-001 \
  USER_ID=alice \
  ACCESS_TOKEN="$FRED_ACCESS_TOKEN" \
  SEARCH_POLICY=semantic
```

### Output modes

The CLI uses [Rich](https://github.com/Textualize/rich) for human-readable output on `stderr`, and emits the full result as JSON on `stdout` — so it can be consumed directly by a UI or a script.

| Use case | Command |
|---|---|
| Rich display only | `make score ... > /dev/null` |
| JSON only (for a script or UI) | `make score ... 2> /dev/null` |
| Both (default) | `make score ...` |

---

### `PRESET` override

`PRESET` is optional. By default, the CLI resolves the preset from `agent_tags` in the trace. To force the RAG preset explicitly:

```bash
make score \
  ... \
  PRESET=rag
```

---

## `make rag-scenarios` — Full Campaign

Runs all questions from `tests/rag_dataset.json` against a given agent and scores each one with DeepEval:

```bash
make rag-scenarios \
  BASE_URL=http://127.0.0.1:8000/fred/agents/v2 \
  AGENT_ID=fred.github.rag_expert \
  ACCESS_TOKEN="$FRED_ACCESS_TOKEN" \
  SEARCH_POLICY=semantic \
  > /dev/null
```

Without extra flags, questions run **sequentially** — one at a time.

---

## `USE_TEMPORAL=1` — Parallel Execution

By default, scenarios run one by one. With `USE_TEMPORAL=1`, the CLI starts an **in-memory Temporal server** and runs all scenarios in parallel — no external Temporal server required.

```bash
make rag-scenarios \
  BASE_URL=http://127.0.0.1:8000/fred/agents/v2 \
  AGENT_ID=fred.github.rag_expert \
  ACCESS_TOKEN="$FRED_ACCESS_TOKEN" \
  SEARCH_POLICY=semantic \
  USE_TEMPORAL=1 \
  > /dev/null
```

**Why it matters:** wall-clock time drops from `N × t` (sequential) to `≈ t` (parallel), where `t` is the time for one scenario. For a 5-question dataset with a slow agent (e.g. Aegis with 13 search calls per question), this reduces a 70-minute run to ~14 minutes.

> **Note:** Temporal in-memory mode logs a few harmless `ERROR` messages about queue readers during startup — these can be ignored. They appear because the in-memory server initialises asynchronously.
