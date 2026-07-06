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

```python
# create the campaign row (domain data) — unchanged
result = await service.create_campaign(body, created_by=user.uid, ...)

# start a bus task of kind "evaluation", team-scoped, optionally scheduled
start = await task_service.start(
    StartTaskRequest(kind="evaluation"),
    created_by=user.uid,
    team_id=body.team_id,
    target=TaskTarget(...),               # references the campaign
    scheduled_for=body.scheduled_for,     # native "+7 days" — durable via the executor
)

# bind the DURABLE executor (Temporal) to the task
#   (the executor adapter starts the workflow, then task_service.bind_execution(...))
return CampaignCreatedResponse(campaign_id=result.campaign_id, task_id=start.task_id, ...)
```

### 4.2 Emit lifecycle as `EvaluationTaskEvent`
Replace the private `store.create_event(kind="campaign_...")` with bus
`EvaluationTaskEvent`s, so state/progress flow through the **common state model + SSE +
authz** (`fred_core.tasks`). The existing `tasks/` module is the seam.

### 4.3 Reconciliation instead of polling
Retire `CampaignRunner.run_forever()` (the 5s poll) for production. Run
**`run_reconcile_sweeper(task_service)`** at startup (as knowledge-flow does in `main.py`)
so tasks whose executor died/diverged are driven terminal (failed/cancelled) — no eternal
limbo. (A MEMORY/polling mode may remain only for lightweight local dev.)

### 4.4 Durable backend in production
Production **must** use the **Temporal** scheduler backend, not `MEMORY`. This is what
makes "+7 days" survive redeploys.

### 4.5 Mirror the platform pattern
Wrap `TaskService` in a domain `EvaluationTaskService` (like knowledge-flow's
`IngestionTaskService`), keeping the campaign as the domain object and the bus task as the
lifecycle/scheduling driver.

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
1. Does `scheduled_for` on the bus already flow to a **durable Temporal timer**, or is a
   small executor adapter needed to bind schedule → workflow?
2. What is the **max scheduling horizon** (tie it to the retention window value)?
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
