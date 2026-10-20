## Purpose

Let operators see what an evaluation costs and why it fails: the metrics the worker and the API expose, the logs each failure produces, and how the chart publishes them.

## ADDED Requirements

### Requirement: Worker and API expose a metrics endpoint
When the Prometheus KPI sink is enabled, the worker SHALL serve a Prometheus endpoint, as the API already does. The endpoint SHALL listen on the configured address and port.

#### Scenario: Worker scraped
- **WHEN** the worker runs with the Prometheus sink enabled on port 9000
- **THEN** `GET :9000/metrics` on the worker pod answers with the evaluator's metrics

### Requirement: Model calls are counted on the platform's LLM metric names
Every model call attempt SHALL increment `llm.calls_total` and record `llm.call_latency_ms`. Both SHALL carry the labels `model_name`, `llm_role` (`judge` for scoring, `analysis` for run analysis), `status` and `error_code`. `status` SHALL be `ok` for an answered attempt, `retry` for a failed attempt that will be retried, and `error` for the final failed attempt. Time spent waiting for the rate cap SHALL be recorded in `eval.judge_throttle_wait_ms`, with the labels `model_name` and `llm_role`.

#### Scenario: One retry then success
- **WHEN** a judge call is rate-limited once and then answered
- **THEN** `llm.calls_total` gains one sample with `status=retry, error_code=rate_limited` and one with `status=ok, error_code=none`, both with `llm_role=judge`

### Requirement: Agent calls and case outcomes are counted
Every agent call SHALL record `eval.agent_call_latency_ms`, with `status` (`ok` or `error`), `error_code` and `http_status` when known. Every finished case SHALL increment `eval.cases_total`, with `status` set to its verdict (`passed`, `failed`, `insufficient`) or to `error` when it could not run.

#### Scenario: Agent timeout
- **WHEN** the agent call times out
- **THEN** `eval.agent_call_latency_ms` records one sample with `status=error, error_code=timeout`, and `eval.cases_total` gains one sample with `status=error`

### Requirement: Metric labels carry no identifiers
Prometheus labels SHALL NOT carry run, case, evaluation, team, user or session identifiers. Those identifiers SHALL appear only in logs.

#### Scenario: Labels of a scored case
- **WHEN** a case is scored and the metrics endpoint is read
- **THEN** no series has a label whose value is the run id, the case id or the team id

### Requirement: Every failure is logged legibly
Each judge-call failure, metric error, agent-call failure and case setup failure SHALL produce one log line carrying the run id, the case id (when there is one), the exception type, the error code, the HTTP status when known, and a non-empty message. When an exception has no message, its type stands in for it. A case setup failure SHALL also log its traceback. A metric error SHALL be logged by the worker, not only stored in the database.

#### Scenario: Timeout with an empty message
- **WHEN** an agent call fails with a timeout exception whose message is empty
- **THEN** the log line names the exception type and `error_code=timeout`, not an empty message

#### Scenario: Metric error
- **WHEN** one metric of a case fails while the others succeed
- **THEN** the worker logs one line naming the metric, the error code and the exception type, and the case's other metrics are stored as usual

### Requirement: One summary line per case
When a case finishes, whether scored or in error, the worker SHALL log one INFO line with the run id, the case id, the verdict, the agent call time, and, for judge calls: their number, retries, failures, total time and total time waited for the rate cap. It SHALL also give the number of metric errors.

#### Scenario: Comparing agent and judge load
- **WHEN** a RAG case with five metrics finishes
- **THEN** its summary line gives the agent call time and the judge call count and time side by side

### Requirement: The chart publishes the metrics endpoint the way Fred's chart does
The chart SHALL enable the Prometheus sink by default on `0.0.0.0:9000`. Whenever the sink is enabled, the API and the worker SHALL each declare a container port named `metrics` and get a `<release>-<component>-metrics` Service exposing it. By default, both pods SHALL carry the `prometheus.io/scrape`, `prometheus.io/port` and `prometheus.io/path` annotations. With `metricsService.serviceMonitor.enabled`, a ServiceMonitor SHALL select those Services and the annotations SHALL be omitted. The chart SHALL fail to render when the sink is enabled on a loopback address.

#### Scenario: Loopback refused
- **WHEN** the chart is rendered with the sink enabled and `address: 127.0.0.1`
- **THEN** rendering fails with a message naming the setting

#### Scenario: Default render
- **WHEN** the chart is rendered with default values
- **THEN** the API and worker containers each declare a port named `metrics` on 9000, each has a metrics Service and the `prometheus.io/*` annotations, and no ServiceMonitor is rendered

#### Scenario: ServiceMonitor instead of annotations
- **WHEN** the chart is rendered with `metricsService.serviceMonitor.enabled: true`
- **THEN** one ServiceMonitor selects both metrics Services on port `metrics`, and the pods carry no `prometheus.io/*` annotations

#### Scenario: Sink disabled
- **WHEN** the chart is rendered with the sink disabled
- **THEN** no `metrics` port, metrics Service, annotation or ServiceMonitor is rendered
