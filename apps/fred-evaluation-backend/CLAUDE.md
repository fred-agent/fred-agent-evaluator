# CLAUDE.md (Fred Evaluation Backend Workspace)

When this folder is opened as the workspace root, apply repository-wide instructions from:

- [`../../CLAUDE.md`](../../CLAUDE.md)
- [`../../docs/DEVELOPER_CONTRACT.md`](../../docs/DEVELOPER_CONTRACT.md)
- [`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)

---

## What this app is

Dedicated evaluation backend for Fred (`EVAL-01`). Owns evaluation campaigns,
datasets, scoring, results, and optional OTel export.

Does **not** own platform identity, teams, permissions, or runtime catalog —
those belong to the Control Plane.

---

## Architecture

```
evaluations/   — immutable, versioned evaluations (API, store, schemas)
runs/          — runs, cases, reports, SSE events, LLM analysis
tasks/         — platform-canonical task API (list, SSE, cancel)
execution/     — Control Plane client, runtime resolution, outbound auth
scoring/       — ScorerPort, DeepEval adapter
workers/       — Temporal workflow and activities
model/         — judge / analysis model factory
telemetry/     — OTel / Langfuse export
migrations/    — Alembic, version table: alembic_version_evaluation
config/        — YAML config loader, PostgresStoreConfig (SQLite in dev)
```

## Key design decisions

- **Separate app** — not inside Control Plane. Each layer owns its domain.
- **`run_id`** — every run of an evaluation gets a `run_id`. Re-running creates a new run without overwriting previous results.
- **SSE** — `GET /runs/{run_id}/events` streams progress events in real time. Reconnectable via `seq`.
- **ScorerPort** — universal interface between the worker and any scorer (DeepEval today, replaceable tomorrow).
- **`PostgresStoreConfig`** — fred-core handles both SQLite (dev) and PostgreSQL (prod) via the same config model.

---

## Base URL

`/evaluation/v1`

## Port

`8336`

---

## Key commands

```bash
make run          # start API (SQLite, no auth)
make rrun         # start API with hot reload
make run-worker   # start evaluation worker
make test         # run unit tests
make code-quality # ruff + format check
```

## First-time setup

```bash
make db-upgrade
make run
```

For a real observability session (security on, against `fred-deployment-factory` infra) rather
than the quick no-auth start above, use the `.claude/skills/live-observability-session` skill at
the repo root — it covers the `configuration.yaml` vs `configuration_prod.yaml` split explicitly,
since `config/.env.template` defaults `CONFIG_FILE` to the standalone profile (commented out).

---

## DB tables

| Table | Description |
|---|---|
| `evaluation` | Immutable, versioned evaluation (name + cases) |
| `question_set` | Reusable question sets |
| `evaluation_run` | One execution of an evaluation |
| `evaluation_case` | Individual test case with input/output/verdict |
| `evaluation_metric_result` | Per-metric scorer result |
| `evaluation_event` | SSE progress events emitted by the worker |
| `evaluation_export_delivery` | OTel/MLflow/Langfuse export delivery tracking |
