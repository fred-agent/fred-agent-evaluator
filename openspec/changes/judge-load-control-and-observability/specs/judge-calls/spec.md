## Purpose

Bound the load the evaluator puts on judge and analysis models: how often a model call is retried, how fast calls are issued, and how each failure is classified.

## ADDED Requirements

### Requirement: Retry only transient failures, a bounded number of times
A judge or analysis model call SHALL be attempted at most `max_attempts` times. Only transient failures SHALL be retried: rate limiting (HTTP 429), provider server errors (HTTP 5xx), timeouts and connection errors. Authentication errors, other HTTP 4xx errors and unparseable answers SHALL NOT be retried. No retry layer other than this policy SHALL add attempts.

#### Scenario: Rate limited once, then answered
- **WHEN** the provider answers 429 to a call and then answers normally, with `max_attempts` of 2
- **THEN** exactly two requests reach the provider and the metric is scored

#### Scenario: Persistent timeout
- **WHEN** every attempt times out, with `max_attempts` of 2
- **THEN** exactly two requests reach the provider and the metric is recorded as an error with code `timeout`

#### Scenario: Invalid credentials
- **WHEN** the provider answers 401
- **THEN** exactly one request reaches the provider and the metric is recorded as an error with code `auth_error`

#### Scenario: Unparseable answer
- **WHEN** the provider answers with content that is not the expected JSON
- **THEN** exactly one request reaches the provider and the metric is recorded as an error with code `invalid_json`

### Requirement: Attempts, timeout and rate are set per model profile
Each model profile (a judge profile, or the analysis model) SHALL accept `max_attempts` (default 2), `request_timeout` in seconds (default 60) and `max_calls_per_minute` (default 60) in its settings. A value below 1 SHALL be rejected when the configuration loads.

#### Scenario: Defaults apply
- **WHEN** a judge profile sets none of the three settings
- **THEN** calls through it use 2 attempts, a 60-second timeout and at most 60 calls per minute

#### Scenario: Invalid value
- **WHEN** a profile sets `max_attempts: 0`
- **THEN** the process fails at startup with a message naming the profile and the setting

### Requirement: Calls per minute are capped per process
Within one worker or API process, calls through a given model profile SHALL NOT exceed its `max_calls_per_minute` in any 60-second window, whatever the number of cases, metrics or concurrent activities. The time a call waits for the cap SHALL NOT count toward its timeout and SHALL NOT be reported as a failure.

#### Scenario: Burst of metric steps
- **WHEN** one case needs 22 judge calls through a profile capped at 10 calls per minute
- **THEN** no 60-second window contains more than 10 of those calls, and every call that waited is still scored normally

### Requirement: Failures are classified into a closed set
Every failed model call SHALL be classified as one of `rate_limited`, `timeout`, `connection_error`, `auth_error`, `provider_http_error`, `invalid_json` or `unknown`, and SHALL carry the HTTP status when the provider returned one. The classification SHALL be the code stored with a metric error.

#### Scenario: Server error
- **WHEN** the provider answers 503 on every attempt
- **THEN** the failure is classified `provider_http_error` with HTTP status 503

### Requirement: Scoring does not block the worker
Scoring a case SHALL NOT block the worker's event loop. Other work on the worker (Temporal polling, other activities, the metrics endpoint) SHALL keep running while judge calls are in flight.

#### Scenario: Long scoring
- **WHEN** a case's scoring takes several minutes
- **THEN** a coroutine scheduled on the worker's event loop during that time runs without waiting for the scoring to finish

### Requirement: Supported providers
Judge and analysis profiles SHALL use one of the providers `litellm`, `vertex_ai` (alias `vertex`) or `ollama`. An `openai` profile SHALL be rejected when the configuration loads. The error message SHALL explain that an OpenAI-compatible endpoint is configured as `litellm` with an `openai/` model prefix and `base_url`.

#### Scenario: Legacy openai profile
- **WHEN** a judge profile declares `provider: openai`
- **THEN** the process fails at startup with that explanation
