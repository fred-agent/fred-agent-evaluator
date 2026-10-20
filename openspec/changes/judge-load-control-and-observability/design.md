## Context

- Judge and analysis models are built by `model/factory.py::build_judge_model`, which returns DeepEval's `LiteLLMModel`, or `GPTModel` for `openai`. The worker image installs the backend lock, which resolves DeepEval 4.0.6. (The library's own lock, 3.9.9, only serves the standalone CLI.)
- In 4.0.6, `LiteLLMModel`'s public methods (`generate`, `a_generate`, `generate_raw_response`, `a_generate_raw_response`) run its transport methods (`_generate`, `_a_generate`, `_generate_raw_response`, `_a_generate_raw_response`) through `_run`/`_arun`. That layer combines a tenacity retry with a per-attempt deadline (about 88 s by default). For LiteLLM the error policy is `None`, so **there are no retries**: a 429 fails the metric at once. The deadline runs each sync call in a dedicated thread, which keeps running once the deadline has passed. LiteLLM's own `request_timeout` (30 s today) expires first. The factory's `num_retries=0` also turns LiteLLM's retries off.
- The worker builds a new judge for every case (`workflow.py::run_case_for_run`, `runner.py`). Any shared state, such as the rate cap, must therefore live outside the model instance.
- `score_trace` is synchronous (`async_mode=False`) and is called directly inside the async `_execute_and_score_case_inner`. That function is shared by the Temporal path and the in-memory runner.
- The worker has no KPI writer. The API builds one (`main.py`) and starts the exporter itself, but the chart declares no metrics port.
- fred-core's Prometheus store keeps only allow-listed labels. `model_name`, `llm_role`, `status`, `error_code`, `exception_type` and `http_status` are already on the list.
- The API image does not install `fred-deepeval-cli`, but it does have DeepEval and LiteLLM. Anything the analysis model also needs must therefore live in the backend package, not in the library.

## Goals / Non-Goals

**Goals:**
- One retry policy and one rate cap for every model call the evaluator makes, in the worker and in the API.
- Enough KPIs and logs to tell, per run and per case, how much load the agent receives compared with the judge.

**Non-Goals:**
- A rate cap shared across replicas. The cap is per process; the chart's default is one worker replica.
- Fewer judge calls per metric (skipping the justification, capping chunks, caching GEval steps). That comes once the KPIs show where the calls go.
- The standalone CLI's `judge_factory.py`, which keeps DeepEval's retries.
- Deleting the in-memory runner, which duplicates the Temporal path. That is a separate consolidation change.
- A Grafana dashboard.

## Decisions

### D1 — Replace DeepEval's call wrapper through a subclass, not a rewrite
A `BoundedLiteLLMModel(LiteLLMModel)` overrides the four public methods. Each override calls the matching transport method directly (`self._generate`, and so on), inside our own retry, rate cap and KPI wrapper. This skips `_run`/`_arun`, so it skips both the retry layer and the per-attempt deadline thread. Otherwise that deadline would also count the time spent waiting for the rate cap, and would leave abandoned threads behind. DeepEval keeps doing prompt building, schema parsing, cost accounting and multimodal handling.
- *Write our own `DeepEvalBaseLLM` on top of `litellm.completion`*: this re-implements parsing, cost and the logprobs path that GEval uses. It is more code to own.
- *Configure DeepEval through `DEEPEVAL_*` variables*: there is no policy for LiteLLM, so no setting enables transient-only retries. The deadline can only be turned off globally, and none of it emits KPIs.
- *Monkeypatching DeepEval*: this is global and invisible at the call site.

Trade-off: the transport methods are DeepEval internals (the gateway contract in 4.x). A test asserts that a failing call reaches the provider exactly `max_attempts` times, so a DeepEval upgrade that renames them fails the tests.

### D2 — Retry waits
Waits grow exponentially with jitter: 2 s, then 4 s, and so on, capped at 30 s. A `Retry-After` header is honoured when LiteLLM exposes it. The sync path sleeps in its thread; the async path uses `asyncio.sleep`. Every attempt, retries included, passes through the rate cap. A failed attempt carries its classification (`error_code`, `http_status`) as attributes on the original exception, which is never wrapped. Wrapping would change the types DeepEval catches; GEval, for instance, falls back on `AttributeError`. The library's scorer reads those attributes by duck typing, since it cannot import the backend.

### D3 — Rate cap: smooth spacing, per profile, per process
Calls through a profile are spaced at least `60 / max_calls_per_minute` seconds apart. The next slot is reserved under a `threading.Lock`, and the caller then sleeps outside the lock. This serves the scoring thread and the async analysis path alike. The limiter registry is module-level and keyed by `(provider, name)`, so the judges rebuilt for each case share one limiter.
- *Token bucket*: it allows a burst at the start, which is precisely what trips provider quotas.
- *A cap shared through Redis or Temporal*: excluded (see Non-Goals).

### D4 — Error classification is ours, using fred-runtime's vocabulary
One classifier maps LiteLLM exceptions (`RateLimitError`, `Timeout`, `APIConnectionError`, `AuthenticationError`, `BadRequestError`, `InternalServerError`/`ServiceUnavailableError`, `APIError.status_code`), httpx exceptions from the agent call, and parse errors to the closed set in `specs/judge-calls`.
- *fred-runtime's `classify_error`*: it would add a fred-runtime dependency to the backend. It also maps `litellm.Timeout`, an `APIConnectionError` subclass, to `connection_error`.

Where codes overlap (`rate_limited`, `provider_http_error`, `connection_error`), they match fred-runtime's. One deliberate divergence: a single `timeout` code, where fred-runtime has `read_timeout`, `connect_timeout` and so on.

### D5 — KPIs on the runtime's metric names
The worker builds its writer with `build_kpi_writer(service_name="fred-evaluation-worker")` and starts the exporter the same way `main.py` does. The writer reaches the judge factory and the activity context. The emitter is `KPIActor(type="system")`. Reusing `llm.calls_total` and `llm.call_latency_ms` means one Grafana query covers agent and judge calls, split by `llm_role` and by the scrape's `app`/`job` label. `status=retry` is a new value. Dashboards that filter `status="error"` keep counting only final failures.

### D6 — Per-case judge statistics through a context variable
Before scoring, the activity sets a context variable holding a mutable `JudgeCallStats`. `asyncio.to_thread` copies the context into the scoring thread, so the wrapper's increments land in the object the activity reads afterwards for the summary line.
- *Passing the stats through `score_trace`*: this changes the library's API for an operational concern.

### D7 — Scoring in a thread, dead executor deleted
`_execute_and_score_case_inner` awaits `asyncio.to_thread(score_trace, ...)`, which covers both engines. Every activity is `async def`, so the `ThreadPoolExecutor` passed as `activity_executor` in `main_worker.py` never runs anything and is deleted.

### D8 — Provider and settings validated at load
A validator on `EvaluationConfig` checks every judge profile and the analysis model:
- the provider is one of `litellm`, `vertex_ai`/`vertex` or `ollama` (`openai` gets a pointer to `litellm`);
- `max_attempts`, `request_timeout` and `max_calls_per_minute` are each at least 1.

A misconfigured profile then fails at startup instead of failing every case. The `GPTModel` branch is deleted.

### D9 — The chart is scraped exactly like Fred's applications
A helper reads `configuration.observability.kpi.prometheus`. If the sink is enabled, it emits a `metrics` port; on a loopback address it calls `fail`. Both pods use the helper. Defaults: `enabled: true`, `address: 0.0.0.0`, `port: 9000`. What follows mirrors Fred's chart, so that production scrapes the evaluator the way it already scrapes Fred:
- one `<release>-<component>-metrics` Service per pod, as knowledge-base does;
- by default, the `prometheus.io/*` pod annotations;
- with `metricsService.serviceMonitor.enabled`, a ServiceMonitor instead of the annotations.

The k3d Prometheus also scrapes every port named `metrics`.

### D10 — Log shape
Lines use fred-runtime's `event=<name> key=value` form: `event=judge_call_failed`, `event=metric_error`, `event=agent_call_failed`, `event=case_setup_failed` (with traceback, via `logger.exception`) and `event=eval_case_done`. An empty exception message is replaced by the exception type.

## Risks / Trade-offs

- [Fewer retries surface more metric errors] → This is intended: they become visible in KPIs and logs instead of tripling latency. `max_attempts` is set per profile.
- [The default cap of 60/min slows large runs: a 22-call RAG case spends at least 22 s on the judge] → Documented in the chart README. Raise it per profile once the provider quota is known.
- [`request_timeout` goes from 30 s to 60 s, so a dead provider hangs longer per attempt] → Fewer false timeouts on long faithfulness prompts. Worst case: `max_attempts × 60 s` per call.
- [A DeepEval upgrade renames the transport methods] → The attempt-count test fails (D1).
- [`max_attempts: 2` adds one retry where 4.0.6 has none, so more load on a 429] → Every attempt goes through the rate cap, and retries are counted (`status=retry`).
- [The cap is per process, so N replicas means N × the cap] → Stated in values and README, as `max_concurrent_cases` already is.

## Migration Plan

- Config: an `openai` judge or analysis profile must become `provider: litellm` with `name: openai/<model>` and `settings.base_url`. The shipped configurations only mention `openai` in comments. A deployment that uses it fails at startup with that instruction.
- Chart 1.3.0 (minor): metrics are on by default. Overlays that set `address: 127.0.0.1` now fail to render, which is intended. Rollback means redeploying chart 1.2.0.

## Open Questions

- Which provider serves as the production judge (Mistral or Vertex Gemini)? This does not change the design. It decides the first `max_calls_per_minute` worth setting in the production overlay.
