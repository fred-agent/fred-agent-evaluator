# SQL Evaluation in `fred-deepeval-cli`

## Context

`fred-deepeval-cli` can be used to evaluate SQL-oriented Fred agent runs through `/agents/evaluate`.

For `fred.github.sql_expert`, evaluating only the final answer is not sufficient. A response can look plausible while:

- no schema inspection was performed,
- no SQL query was executed,
- a join or aggregation was incorrectly formed,
- the final answer does not match the actual query result.

For that reason, the current SQL evaluation flow combines two complementary layers:

1. structural checks on observable SQL behavior;
2. factual checks on the actual `read_query` result.

---
## Current Availability of the SQL Agent

At the moment, `fred.github.sql_expert` is exposed only in the `1606-expose-sql-agent-in-fred-agents` branch of `fred-agents`, in PS mode.

To test the SQL evaluation flow from `fred-deepeval-cli`, `fred-agents` must therefore be started locally from that branch.

In practice:
- switch `fred-agents` to branch `1606-expose-sql-agent-in-fred-agents`;
- start the local agent runtime from that branch;
- then run the evaluation commands from `fred-deepeval-cli`, for example:

```bash
make sql-scenarios \
  BASE_URL=http://127.0.0.1:8000/fred/agents/v2


## Goal

The goal of the current implementation is to provide a first practical SQL-aware evaluation layer for local development, built around a dedicated profile named `sql` for the agent `fred.github.sql_expert`.

It is designed to answer two complementary questions:

- Did the run exhibit the expected SQL behavior?
- Did the run return the expected SQL result?

---

## Profile Recognition

The CLI resolves the `sql` preset from `agent_tags` in the trace. When `agent_tags` contains a tag that maps to the `sql` preset, the CLI applies SQL-specific structural checks automatically.

An explicit `PRESET=sql` override remains available to force preset resolution regardless of `agent_tags`.

---

## Files

The SQL scenario flow currently relies on two files:

- [`tests/sql_scenarios.json`](../tests/sql_scenarios.json)
- [`scripts/run_sql_scenarios.py`](../scripts/run_sql_scenarios.py)

---

## Layer 1 — SQL Flow Structural Checks

### Overview

Two structural checks are currently defined to validate observable SQL behavior.

### `sql_query_executed_ok`

Answers: **did the agent execute a real SQL query?**

Does not rely on `tools_called` alone, as that only indicates a tool was attempted.

Signal used: `steps`

Logic:

- verify the presence of a `tool_call` to `read_query`,
- and ideally a non-error `tool_result` associated with it.

### `sql_no_execution_error_ok`

Answers: **did the query execute without error?**

Errors can appear in multiple forms, so this check aggregates several signals:

- `trace["error"]` — global execution error,
- `node_error` in `steps` — degraded execution path,
- `tool_result.is_error` — tool-level error,
- textual content of `tool_result` — e.g. messages starting with:

```
"Error: Error calling read_query. Status code: 500 ..."
```

This check is therefore broader than a simple `trace["error"] is None`.

### Structural Tests

Two options exist for organizing structural tests:

- extend the existing file: `tests/test_structural_checks.py`
- or create a dedicated file: `tests/test_sql_structural_checks.py`

The second option is recommended to clearly isolate SQL logic.

---

## Layer 2 — Factual Correctness

### Step 1 — Define SQL Scenarios

`tests/sql_scenarios.json` contains the structured SQL scenarios executed against `fred.github.sql_expert`.

Each scenario includes:

#### `input`

The user question sent to the agent.

Example:

```json
"input": "What is the total revenue by category in commandes?"
```

#### `expected_flow`

The expected observable execution behavior.

Example:

```json
"expected_flow": {
  "query_executed": true
}
```

Current fields:

- **`query_executed`**
  - `true`: a `read_query` execution is expected
  - `false`: no SQL query is expected

#### `tags`

Descriptive labels used to classify the scenario.

Example:

```json
"tags": ["join", "aggregation", "region"]
```

Supported tags: `metadata`, `join`, `aggregation`, `support`, `ambiguity`, etc.

---

### Step 2 — Validate the Expected SQL Flow

`scripts/run_sql_scenarios.py` reads the scenario file, executes every scenario against `fred.github.sql_expert`, and compares the expected flow with the structural checks returned by `fred-deepeval-cli`.

This validates the first evaluation layer:

- SQL execution happened when expected,
- no SQL execution error occurred.

The runner compares:

- `expected_flow.query_executed`

against the structural check already produced by the CLI:

- `sql_query_executed_ok`

This transforms manual prompts into a replayable scenario campaign.

---

### Step 3 — Validate Factual Correctness with `expected_values`

Some scenarios are enriched with an `expected_values` block. This second layer checks whether the actual SQL result is factually correct.

Current supported fields:

#### `row_count`

The exact number of rows expected in the SQL result.

```json
"row_count": 10
```

#### `first_row`

A subset of expected values for the first returned row.

```json
"first_row": {
  "nom": "Moreau",
  "prenom": "Pierre",
  "total_revenue": 6307.83
}
```

#### `contains_rows`

Rows that must appear somewhere in the SQL result.

```json
"contains_rows": [
  { "categorie": "mode", "total_revenue": 18634.73 }
]
```

#### `output_contains`

Text fragments that must appear in the final answer.

```json
"output_contains": ["548.7"]
```

`scripts/run_sql_scenarios.py` is extended to compare these expected values against the actual `read_query` result, verifying not only that the agent follows the right flow but that the SQL output is factually correct.

---

### Step 4 — Explicit Join Validation with `sql_query_contains`

For join-oriented scenarios, `expected_values` can also contain `sql_query_contains`.

This field verifies that the executed SQL query contains expected structural fragments such as:

- `JOIN`
- `c.id_client = d.id_client`
- `code_postal`
- `GROUP BY`
- `SUM(c.montant)`

Example:

```json
"sql_query_contains": [
  "JOIN",
  "c.id_client = d.id_client",
  "SUM(c.montant)"
]
```

For a join scenario, this enables validation at three levels:

1. the SQL flow happened;
2. the executed SQL query contains the expected join structure;
3. the returned result matches the expected rows or values.

---

## Observed Values in Runner Output

The runner outputs a compact summary of what was actually observed for each scenario.

Current `observed_values` fields:

- `sql_query`
- `query_row_count`
- `query_first_row`

This makes the campaign output easier to inspect, especially for joins and aggregations.

---

## Command

The SQL scenario campaign can be run with:

```bash
make sql-scenarios \
  BASE_URL=http://127.0.0.1:8000/fred/agents/v2
```

Optional variables:

- `USER_ID`
- `TEAM_ID`
- `ACCESS_TOKEN`

---

## Interpretation

A passing scenario means:

- the expected SQL flow was observed,
- the query result matched the declared factual expectations,
- and, for joins, the executed SQL could be checked explicitly.

This makes it possible to distinguish:

- a metadata-only answer,
- a correct SQL execution,
- a correct join result,
- and a good-looking answer without observable SQL behavior.

---

## Current Scope

The current implementation provides a practical V1 for SQL evaluation in local development.

It already supports:

- metadata scenarios,
- simple queries,
- aggregations,
- joins,
- ambiguous prompts,
- factual result assertions,
- explicit checks on join-related SQL fragments.

Promptfoo or broader dataset-driven orchestration can be explored later if the campaign needs to become more industrialized.