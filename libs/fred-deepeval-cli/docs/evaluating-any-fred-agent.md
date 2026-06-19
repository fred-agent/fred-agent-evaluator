# Evaluating Any Fred Agent Pod

## Prerequisites — minimum versions

`agent_tags` was added to `EvalTrace` in **fred-sdk 2.0.6** and **fred-runtime 2.0.7**.

Pods running older versions will return an `EvalTrace` without the `agent_tags` field. The CLI falls back to `preset: "default"` and only computes `AnswerRelevancy` — all contextual RAG metrics (`Faithfulness`, `ContextualRelevancy`, `ContextualPrecision`, `ContextualRecall`) will be missing.

**Before running a campaign against any pod, verify the installed versions:**

```bash
curl -s <BASE_URL>/agents/evaluate \
  -X POST -H "Content-Type: application/json" \
  -d '{"agent_id":"<AGENT_ID>","input":"test","session_id":"version-check","runtime_context":{"user_id":"alice"}}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('agent_tags:', d.get('agent_tags','MISSING — upgrade fred-sdk/fred-runtime'))"
```

For `dt-agents`, install the local sources before starting the pod:

```bash
cd dt-agents/agents
make dev-local   # installs fred-sdk>=2.0.6 and fred-runtime>=2.0.7 from ../../fred/libs
```

> **Note:** `make run` uses `uv run` which re-syncs from `uv.lock` on every startup and will revert editable installs. Start the pod with the venv activated instead:
> ```bash
> source .venv/bin/activate
> ENV_FILE=config/.env python -m fred_dt_agents
> ```

---

## Overview

`fred-deepeval-cli` can evaluate any agent pod built on `fred-runtime` — including `dt-agents` — without any modification to the CLI itself.

---

## How It Works

Any pod that calls `create_agent_app()` from `fred-runtime` automatically exposes the `POST /agents/evaluate` endpoint. This endpoint:

1. Executes the agent normally
2. Collects all runtime events produced during execution (tool calls, retrieval results, final answer, errors)
3. Assembles them into an `EvalTrace` object — defined in `fred-sdk` — and returns it as JSON

```
fred-runtime
    └── create_agent_app()
            └── POST /agents/evaluate
                    ├── runs the agent
                    ├── collects runtime events
                    └── returns EvalTrace {
                            input, output,
                            retrieval_context,
                            tools_called,
                            agent_tags,
                            steps, latency_ms, ...
                        }
```

`fred-deepeval-cli` calls this endpoint via `fetch_trace()`, reads the `agent_tags` to automatically detect the evaluation preset (`rag`, `sql`, or `default`), and passes the trace to DeepEval for scoring.

---

## Role of `agent_tags`

Tags are declared in the agent definition and carried inside the `EvalTrace`:

```python
# Example: Aegis in dt-agents
tags = ("aegis", "rag", "c-rag", "self-rag", "graph", ...)
```

The CLI's `preset_resolver` reads these tags and selects the appropriate metrics automatically:

| Tag detected | Preset | Metrics enabled |
|---|---|---|
| `rag` | `rag` | AnswerRelevancy, Faithfulness, ContextualRelevancy, ContextualPrecision, ContextualRecall |
| `sql` | `sql` | SQL structural checks |
| none | `default` | AnswerRelevancy only |

---

## Example: Evaluating Aegis (`dt-agents`)

Aegis is a C-RAG + Self-RAG graph agent that uses Knowledge Flow for document retrieval.
It declares the `rag` tag → the RAG preset is detected automatically → all 5 DeepEval metrics apply.

### Services to start (3 terminals)

```bash
# Terminal 1 — Knowledge Flow (port 8111)
cd fred/knowledge-flow-backend && make run

# Terminal 2 — dt-agents (port 8020)
cd dt-agents/agents && make run

# Terminal 3 — evaluation (fred-deepeval-cli)
```

### Single-turn evaluation

```bash
make score \
  BASE_URL=http://127.0.0.1:8020/dt/agents/v1 \
  AGENT_ID=fred.dt.aegis.graph \
  INPUT="What does the technical policy require before production deployment?" \
  SESSION_ID=aegis-$(date +%s) \
  USER_ID=alice \
  ACCESS_TOKEN="$FRED_ACCESS_TOKEN" \
  > /dev/null
```

### Full campaign

```bash
make rag-scenarios \
  BASE_URL=http://127.0.0.1:8020/dt/agents/v1 \
  AGENT_ID=fred.dt.aegis.graph \
  ACCESS_TOKEN="$FRED_ACCESS_TOKEN" \
  > /dev/null
```

---

## Evaluating Other Pods

The same pattern applies to any other `fred-runtime`-based pod. Simply change `BASE_URL` and `AGENT_ID`:

| Pod | BASE_URL | AGENT_ID example |
|---|---|---|
| `fred-agents` | `http://127.0.0.1:8000/fred/agents/v2` | `fred.github.rag_expert` |
| `dt-agents` | `http://127.0.0.1:8020/dt/agents/v1` | `fred.dt.aegis.graph` |
| any other pod | `http://127.0.0.1:<port>/<base_url>` | as declared in the pod config |

The CLI adapts automatically — no code change required.
