---
name: live-observability-session
description: Start fred-evaluation-backend's API and worker and watch their logs live while the developer drives an evaluation campaign by hand (via Swagger, the control-plane-mediated flow, or a direct API call). Use for manual observability sessions on this backend, or to check "does X actually log/emit correctly" against fred_core's stdout(+audit) model.
user-invocable: true
argument-hint: [optional: api-only, worker-only, or both — default both]
---

# Live Observability Session (fred-agent-evaluator)

A **collaborative** working mode, not an automated test run: the developer drives Swagger or an
evaluation campaign by hand; you start the API and worker, tail their stdout, and report what you
see. You never call a business endpoint or launch a campaign yourself — see "The protocol" below.
This mirrors `~/Fred/fred/.claude/skills/live-observability-session/SKILL.md` (the canonical
version, same protocol, same three-stream model), which already documents how to run this same
backend as a *fourth app* when a session is launched from the `fred` repo — this version is for
working in `fred-agent-evaluator` directly, as its own repo/session.

**Scope: this targets the fred-agent-evaluator repo (`~/Fred/fred-agent-evaluator`), on top of the
same `fred-deployment-factory` local dev stack fred's own skill uses.** If the developer is on a
different deployment target, ask before assuming any of the below still holds.

## The one rule this skill exists to enforce: always `configuration_prod.yaml`

**A live observability session is a security-on, `fred-deployment-factory`-backed session, full
stop — never the standalone `configuration.yaml`.** Both API and worker read `CONFIG_FILE` from
`apps/fred-evaluation-backend/config/.env`. As committed, `config/.env.template` ships with
`CONFIG_FILE` **commented out** (defaulting to standalone — SQLite, no auth — the repo's own
quick-start persona: `make run` with zero infra). Before starting anything:

    grep CONFIG_FILE apps/fred-evaluation-backend/config/.env

Confirm it's uncommented and reads:

    CONFIG_FILE="./config/configuration_prod.yaml"

If it's missing, commented out, or points at `configuration.yaml`, **fix it and say so** rather
than asking permission — `.env` is a local, gitignored file meant to be edited per session. The
worker additionally needs `make run-worker-prod` (not plain `run-worker`) — that target explicitly
exports `CONFIG_FILE=./config/configuration_prod.yaml` and enables M2M against Keycloak, matching
the API side. For the API, plain `make run` is enough once `.env`'s `CONFIG_FILE` is correct — the
app reads it from `config/.env` regardless of which target launched it.

## Preconditions — infra is the developer's job, not yours

Postgres, Keycloak, Temporal (and the rest of the platform: control-plane, a runtime pod) run via
docker compose / `make run` in `~/Fred/fred-deployment-factory` and `~/Fred/fred` respectively —
this app's prod profile assumes: **PostgreSQL on `localhost:5432`, Control Plane on
`localhost:8222`, a runtime pod on `localhost:8000`, Temporal on `localhost:7233`**, with
`fred-deployment-factory` mapping `app-keycloak` to the local Keycloak endpoint during compose
setup. **Do not start, stop, or wipe this infra yourself** — confirm with the developer that
whichever pieces this session needs are up before starting the API/worker. If the session is
evaluation-only (no real campaign against a live agent), the control-plane/runtime pod pieces may
not be needed — ask rather than assuming the full stack is required.

## Starting the backends

| App | Command | Port | Notes |
|---|---|---|---|
| `apps/fred-evaluation-backend` (API) | `make run` (from `apps/fred-evaluation-backend`) | 8336 | Base path `/evaluation/v1`. (Some docs/READMEs in this repo still say `:8333` — stale; the real port, confirmed in both `configuration.yaml` and `configuration_prod.yaml`, is `8336`.) |
| `apps/fred-evaluation-backend` (worker) | `make run-worker-prod` | — (no HTTP) | Never expose the worker via HTTP — it accesses the DB directly, per this repo's `CLAUDE.md` rule #4. Runs scoring via `fred-deepeval-cli`; the API itself never runs scoring (rule #5) — if you're chasing a "score didn't compute" report, the worker's stdout is where that happens, not the API's. |

Launch both in parallel — independent Bash calls in one message, each `run_in_background: true` —
unless the developer's question is scoped to just one side (e.g. "did the API log this request
correctly" doesn't need the worker up).

`make run`/`make run-worker-prod` install deps first if needed — the first launch after a clean
checkout will be slower; don't mistake that for a hang. The worker specifically needs the
`dev-scoring` extra installed (`make run-worker` depends on it) — if you see it pulling in DeepEval
dependencies on first launch, that's expected, not a sign something's misconfigured.

## Watching, don't polling

Use the **Monitor** tool against each background shell to stream stdout live — every line becomes
a notification — rather than periodically re-reading a log file. This lets you correlate "developer
just launched/checked a campaign" with the log line it produced in near real time. Stop every
Monitor you started once the developer is done.

## Metrics and OpenSearch — deliberately off in this app, in every profile

Unlike the other Fred backends, `fred-evaluation-backend` explicitly disables **both** Prometheus
and OpenSearch KPI sinks even in `configuration_prod.yaml`:

    observability:
      kpi:
        log:
          enabled: true
        prometheus:
          enabled: false
        opensearch:
          enabled: false

`curl localhost:<any port>/metrics` will 404 — don't report that as broken, it's this app's own
deliberate config, not a bug or a missing override. Its only live signal in any profile is its own
stdout (Monitor it the same way as any other backend) plus whatever it writes to Postgres/Temporal
directly. If a session ever needs KPIs from this app, that's a real config change (flip
`prometheus.enabled: true`, pick a port following the `<api-port>+1000` convention other Fred pods
use — `9336` is free) — flag it as a decision for the developer, don't just enable it.

## The three streams — what "checking observability" actually means

This app depends on published `fred-core`, which ships the same `StoreEmitHandler`/
`AUDIT_LOGGER_NAME` mechanism the rest of the platform uses:

1. **stdout** — API and worker each have their own console handler; also where the audit logger
   writes exclusively, as structured JSON, `propagate=False`. Audit records must appear here and
   **only** here.
2. **OpenSearch** — not fed by this app in any profile (see above) — don't go looking for its logs
   there.
3. **KPIs/metrics** — none in any profile (see above).

## The protocol

- The developer drives Swagger or a real evaluation campaign. You do not call a business endpoint
  or launch/score a campaign yourself. If a specific action would help diagnose something, propose
  it and let the developer perform it, or ask before running it yourself.
- When the developer reports something, diagnose from the logs **first** — don't guess at a root
  cause before reading what actually happened.
- Report every finding with all four of: **reproduction**, **extract** (quote the actual log
  line, don't paraphrase), **channel** (stdout / audit — OpenSearch and KPIs are not in scope for
  this app, see above), and **classification** (bug, config gap, expected-but-underdocumented
  behavior, or false alarm).
- Fix the root cause, not a patch over the symptom, and respect this repo's `CLAUDE.md` boundary
  rules while doing so (never blur the API/worker split, never add scoring deps to the API image,
  `fred-core`/`fred-sdk` come from PyPI — no local path overrides).

## Ending the session

Stop whichever background processes and Monitors this session started when the developer is done.
Don't leave them running silently across an unrelated task.

## Before starting anything — check for stale processes

    ss -ltnp | grep -E ':8336'

If the port is already held, find the owning PID and check whether its parent is a **still-running**
process before touching it. Only kill processes confirmed stale. The worker has no listening port
to check this way — if in doubt whether one is already running, `ps aux | grep main_worker`.
