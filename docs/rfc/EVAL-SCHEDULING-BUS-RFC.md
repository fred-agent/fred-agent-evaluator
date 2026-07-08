# RFC EVAL-02 — Route evaluation scheduling through the common task-event bus + durable scheduler

**Status:** draft for discussion
**Author:** Odelia Cohen
**Reviewers:** Dimitri Tombroff (runtime/control-plane, scheduler), Evaluation backend owner
**Track:** `EVAL-02` (Evaluator task-event adoption)
**Related:** fred `TASK-EVENT-STREAM-RFC.md` (`EvaluationTaskEvent`/`EvaluationDetail`),
`FRED-2.0.2-RGPD-READY-RFC.md` / "erasure you can prove" (retention window = evaluation window),
`EVAL-DATASET-RFC.md`, `EVAL-AUTH-RFC.md`

---

## 1. Decision requested

Agree that **any action that schedules or runs an evaluation must go through the same
task-event bus and scheduler abstraction used by control-plane and knowledge-flow**
(`fred_core.tasks` + `fred_core.scheduler`), rather than the evaluator's current bespoke
polling runner + private event store. And agree on the **RGPD bounds** that follow
(retention coverage + a maximum scheduling horizon).

This is Dimitri's requirement, restated: *homogeneous* (same bus), *durable* (a campaign
scheduled for +7 days still runs in 7 days across redeploys), and *time-bounded* (a stuck
or far-future campaign must not retain personal data indefinitely).

---

## 2. The three concerns this RFC addresses

| # | Concern | Why it matters |
| --- | --- | --- |
| 1 | **Homogeneity** — one common bus | control-plane and knowledge-flow already use `fred_core.tasks`; the evaluator must too (no divergent mechanism to maintain) |
| 2 | **Durability** — schedule survives redeploys | a campaign scheduled for +7 days must run even if the code is redeployed/restarted in between |
| 3 | **RGPD** — bounded data lifetime | captured conversations are personal data; a stuck or far-future campaign must not keep them alive beyond the retention window |

---

## 3. Current state (what exists) and the gap

**Already in place**
- `fred_core.scheduler` is imported (`SchedulerBackend`, `TemporalClientProvider`); a
  Temporal path exists (`CampaignWorkflow`).
- A `tasks/` module already imports `fred_core.tasks` — partial adoption.
- The bus already ships **`EvaluationTaskEvent`** / **`EvaluationDetail`** and a
  reconciliation sweeper (`run_reconcile_sweeper`, `reconcile_stale`).

**The gap — a bespoke system runs in parallel**
- `campaigns/store.py`: private state machine (`update_campaign_state`) + private event
  log (`create_event`) + `list_campaigns_by_state`.
- `workers/runner.py`: `CampaignRunner.run_forever()` — an **asyncio polling loop** (every
  `poll_interval_seconds`) that scans `list_campaigns_by_state("pending")` and launches
  campaigns. This is the default **`MEMORY`** backend — **not durable**, and cannot
  express "run in 7 days" (it only runs what is already `pending`).
- Campaign creation starts a Temporal workflow **directly** (`client.start_workflow(...)`),
  outside the bus — so no unified task lifecycle, no `scheduled_for`, no reconcile binding.

Net: two event systems, a non-durable default trigger, and no time bound.

---

## 4. Proposal — cut over to bus + durable executor + reconcile

### 4.1 Create a campaign as a bus task
Replace the direct `start_workflow(...)` with `TaskService.start(...)`. The bus API
already carries everything we need, including native scheduling:

The order below is not cosmetic. The bus task is opened **first**, because a failure to
schedule must have a real `task_run` row to be recorded against. The binding happens
**last**, because the workflow id does not exist before the workflow is started.

```python
# 1. open the bus task — kind "evaluation", team-scoped, optionally scheduled.
#    The bus mints the task_id (store.new_task_id()); the campaign no longer mints one.
campaign_id = service.new_campaign_id()
started = await task_service.start(
    StartEvaluationRequest(params=StartEvaluationParams(campaign_id=campaign_id)),
    created_by=user.uid,
    team_id=body.team_id,
    target=TaskTarget(type="evaluation_campaign", id=campaign_id, label=body.name),
    scheduled_for=body.execution.scheduled_for,   # native "+7 days"
)

try:
    # 2. persist the campaign (domain data), carrying the bus-minted task_id
    result = await service.create_campaign(body, campaign_id=campaign_id,
                                           task_id=started.task_id, ...)

    # 3. the APPLICATION starts the durable workflow (see §8.1) — the bus cannot
    handle = await client.start_workflow(CampaignWorkflow.run, ...,
                                         start_delay=_start_delay(scheduled_for))

    # 4. bind task ↔ workflow, so reconcile_stale can ask Temporal for its verdict
    await task_service.bind_execution(started.task_id, execution_id=handle.id)

except Exception as exc:
    # Between 1 and 4 the task has no execution_id, and reconcile_stale skips tasks with
    # no execution behind them. Without this, the task sits "pending" forever — the exact
    # limbo this RFC exists to remove.
    await task_service.fail_task(started.task_id, f"could not schedule campaign: {exc}")
    raise
```

### 4.2 Emit lifecycle as `EvaluationTaskEvent`
Publish the campaign lifecycle as bus `EvaluationTaskEvent`s, so state/progress flow
through the **common state model + SSE + authz** (`fred_core.tasks`).

This is **not optional and not cosmetic**. §4.1 alone leaves the database incoherent: the
sweeper finds a task that never reported success, asks Temporal, is told the execution
*completed*, and `_reconciled_terminal` returns `failed` with *"Execution finished without
completing the task"*. Observed on a real run — `evaluation_campaign.operational_state =
completed` while `task_run.state = failed`. `fred_core` is right: a finished execution
whose task never announced success is a failed task. So the worker must announce it.

**Exactly two publications, each at a single-writer moment:**

| When | Where | Event |
| --- | --- | --- |
| before the cases fan out | `mark_campaign_running` activity | `running`, progress 0.0 |
| after they have all joined | `finalize_campaign` | `succeeded`, progress 1.0, full counts |

Failures need no code at all: the sweeper already reflects Temporal's verdict.

The single-writer constraint is a hard one, not a preference. `store.record_event` reads
`task_run.seq` and writes `seq + 1` **without locking the row**, while `task_event_log`
carries `UNIQUE (task_id, seq)`. Two concurrent writers on the same task collide.
Knowledge-flow never meets this because it mints one task per file; a campaign is one task
for N cases, so **`run_case` must never publish** — it runs in `asyncio.gather`. Per-case
progress would require either a row lock in `fred_core` or one task per case (open
question 5).

Note also that `succeeded` is a *task* state, not a *verdict*. `verdict`
(passed/failed/insufficient) stays in `evaluation_campaign`: an agent that scores badly
must not appear as a broken campaign.

### 4.3 Reconciliation instead of polling
Retire `CampaignRunner.run_forever()` (the 5s poll) for production. Run
**`run_reconcile_sweeper(task_service)`** at startup (as knowledge-flow does in `main.py`)
so tasks whose executor died/diverged are driven terminal (failed/cancelled) — no eternal
limbo. (A MEMORY/polling mode may remain only for lightweight local dev.)

### 4.4 Durable backend in production
Production **must** use the **Temporal** scheduler backend, not `MEMORY`. This is what
makes "+7 days" survive redeploys.

### 4.5 Mirror the platform pattern
*Corrected 2026-07-08.* An earlier draft of this section proposed wrapping `TaskService`
in a domain `EvaluationTaskService`, "like knowledge-flow's `IngestionTaskService`". That
rests on a misreading: `IngestionTaskService` does **not** wrap the bus. Its own docstring
says it "wraps scheduler backend selection and orchestration … to keep Temporal client
handling out of the controller layer". Knowledge-flow holds **two** distinct objects:

- `fred_core.tasks.TaskService` — the bus, called **directly** from the controller;
- `IngestionTaskService` — a local **scheduler**: chooses MEMORY/TEMPORAL, owns the
  Temporal client, starts the workflows.

The evaluator already owns the equivalent of the second, merely scattered across
`app.state.temporal_client_provider`, `campaigns/api.py` and `workers/`. So there is
nothing to "wrap". The only useful move is to gather that scattered Temporal code into a
single `EvaluationScheduler`, so the router no longer knows about Temporal. That is a
refactor, not a behaviour change, and it must land **after** §4.1 in its own commit.

---

## 5. RGPD — what the bus does NOT solve by itself

The bus + Temporal + reconcile solves concerns **1 and 2**, and the "stuck task doesn't
linger" half of concern **3**. Two RGPD items remain and must be explicit:

- **5.1 Data erasure of captured conversations.** The bus governs the *task* lifecycle,
  not the *data*. The control-plane **retention policy** ("retention window = evaluation
  window", `erasure you can prove`) must **cover the evaluator's captured
  conversations/QuestionSets/results**, so they are erased at the end of the window
  regardless of task state.
- **5.2 Maximum scheduling horizon.** A campaign *legitimately* scheduled far in the
  future (e.g. +1 year) keeps data alive that whole time — reconcile won't touch it (it
  isn't stuck). We need a **max `scheduled_for` horizon / TTL** so scheduling cannot
  exceed the retention window. Reject or clamp schedules beyond the bound.

---

## 6. Non-goals
- Redesigning the campaign domain model or the evaluation logic.
- The dataset-triage subject (separate `EVAL-TRIAGE` RFC).
- Building a new scheduling mechanism — we adopt `fred_core.tasks` / `fred_core.scheduler`.

---

## 7. Risks
| Risk | Mitigation |
| --- | --- |
| Two systems during migration | migrate creation → bus first; keep reads working; remove bespoke events last |
| MEMORY used in prod by mistake | make Temporal the prod default; assert backend at boot |
| Reconcile closes a healthy long task | grace period tuned; only diverged executions are driven terminal |
| Far-future schedule retains data | max `scheduled_for` horizon (5.2) |
| Erasure misses evaluator data | retention policy explicitly covers eval data (5.1) |

---

## 8. Open questions
1. ~~Does `scheduled_for` on the bus already flow to a **durable Temporal timer**, or is a
   small executor adapter needed to bind schedule → workflow?~~
   **Resolved 2026-07-08 — an adapter is needed; the application starts the workflow.**
   The bus's executor interface (`NoopWorkflowControl` / `TemporalWorkflowControl`) exposes
   only `get_status` and `cancel`: there is no `start`. `fred_core` is shared by three
   backends and cannot know which workflow, which task queue, or which arguments — those
   exist only in the application. So the caller starts the workflow itself, passing
   `start_delay = scheduled_for - now`, and then calls `bind_execution(...)`. This is
   exactly what knowledge-flow does for ingestion (`ingestion_controller.py`), including
   the `fail_task` net when the workflow could not be created. `scheduled_for` on the bus
   is therefore a **record** of the schedule; Temporal owns the timer.
2. What is the **max scheduling horizon** (tie it to the retention window value)?
   *Still open, and deliberately not implemented:* the bound must equal the platform
   retention window, which is a control-plane decision. Hard-coding a number here would
   hide the question rather than answer it. `scheduled_for` is currently unbounded.
3. Who owns **erasure of evaluator data** — the control-plane retention worker, or an
   evaluator-side hook it triggers?
4. Keep a MEMORY/polling mode for local dev, or Temporal-only everywhere?
5. Exact `EvaluationTaskEvent` payload for campaign vs per-case progress.

---

## 9. Acceptance criteria
- A campaign is created via `TaskService.start(kind="evaluation", scheduled_for=…)`, bound
  to a durable Temporal execution; no direct `start_workflow` outside the bus.
- Campaign lifecycle is observable as `EvaluationTaskEvent`s over the common SSE.
- `run_reconcile_sweeper` runs at startup; a killed executor drives its task terminal.
- Production uses the Temporal backend; a +7-day schedule survives a redeploy.
- Scheduling beyond the max horizon is rejected/clamped; captured conversation data is
  erased at the end of the retention window regardless of task state.
