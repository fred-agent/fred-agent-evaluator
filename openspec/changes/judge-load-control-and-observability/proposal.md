## Why

In production, evaluation runs appear to issue far more LLM calls than expected and end in timeouts or errors, while the same runs behave locally. Nothing can confirm it today: the worker emits no KPI and the chart exposes no metrics port. The code shows the load profile: a RAG case with the five built-in metrics costs about 22 judge calls, against 2 to 4 agent LLM calls. These calls are sent back to back, with no cap. The worker's DeepEval (4.0.6) has no retry policy for LiteLLM, so a single 429 or 30-second timeout fails the metric outright. This change implements [issue #59](https://github.com/fred-agent/fred-agent-evaluator/issues/59) to make the evaluator's load bounded and measurable before a first stable version.

## What Changes

- Judge calls follow our own bounded retry policy: a few attempts, only on transient errors (429, 5xx, timeout, connection). DeepEval's call wrapper (its retry layer and its per-attempt timeout thread) is bypassed. The same policy covers the API's run-analysis model.
- A per-process cap on judge calls per minute, so a burst of metric steps cannot hit a provider quota.
- Scoring runs off the worker's event loop.
- The worker starts the fred-core Prometheus exporter and emits judge KPIs on the fred-runtime metric names (`llm.calls_total`, `llm.call_latency_ms`, `llm_role=judge`), plus agent-call latency and case outcomes.
- Errors become legible: every judge, metric, agent-call and setup failure is logged with its exception type, error code and HTTP status. One summary line per case gives agent time, judge calls, retries and judge time.
- **BREAKING (config):** the `openai` judge provider goes through LiteLLM like the others, so the `GPTModel` branch is deleted. An OpenAI-compatible endpoint is configured as `provider: litellm` with an `openai/` model prefix and `base_url`.
- The chart gives the API and the worker a `metrics` container port and refuses an exporter bound to `127.0.0.1`. The exporter is on by default. The pods are scraped exactly like Fred's applications: a metrics Service per pod, `prometheus.io/*` annotations by default, and an optional ServiceMonitor.
- The k3d Prometheus scrapes both pods with no change to fred-deployment-factory, since it already scrapes every port named `metrics`.

## Capabilities

### New Capabilities

- `judge-calls`: how the evaluator reaches judge and analysis models (retry policy, rate cap, error classification) and what it reports about those calls (KPIs, logs).
- `evaluation-observability`: what the worker and the API expose for operators (metrics endpoint, case-level KPIs, error logs, per-case summary) and how the chart publishes it.

### Modified Capabilities

None. `evaluation-ui` is unaffected.

## Impact

- `apps/fred-evaluation-backend`: `model/factory.py` (bounded model, `openai` branch removed), a new small judge-call module (policy, limiter, error classification, KPI and log emission), `workers/activities.py`, `workers/workflow.py`, `workers/runner.py`, `main_worker.py` and `main.py` (shared KPI writer and exporter, `telemetry/kpi.py`), `execution/analysis_client.py`, `config/models.py`, both config files, tests.
- `libs/fred-deepeval-cli`: `core/scorer.py` and `core/models.py` give each metric error its code (`error_code`); the worker logs it. The CLI's own `judge_factory.py` keeps DeepEval's retries (deferred, see design).
- `deploy/charts/fred-evaluator`: worker and API templates, helpers, values, README. The version bump (1.3.0) belongs to the release commit.
- `fred-deployment-factory`: no change; the chart defaults already open the exporter to the k3d Prometheus.
- No API contract change. No fred-core or fred-runtime change: every Prometheus label used is already on fred-core's allow-list.
