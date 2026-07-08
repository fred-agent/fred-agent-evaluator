# RFC EVAL-AUTH — Authentication & authorization model for the evaluation backend

**Status:** draft — direction agreed by the runtime/control-plane owner (Dimitri),
**pending a security review** by other reviewers before being frozen.
**Version:** v1 proposal
**Date:** 2026-06-30
**Authors:** Odelia Cohen, Dimitri Tombroff
**Track:** `EVAL-AUTH`
**Related:** `docs/rfc/EVAL-DATASET-RFC.md` (capture), fred `#1874` (runtime history endpoint)

---

## 1. Decision requested

Approve the identity & authorization model for the two evaluation components, and
in particular **what must be provisioned at platform installation** and **how the
evaluation worker is identified**:

- **Fapi** (fred-evaluation-backend, **API**, interactive) acts **on behalf of the
  user** by propagating the user's JWT.
- **Fworker** (fred-evaluation-backend, **worker**, asynchronous) acts under its
  **own service identity**, with **least-privilege, team-scoped** rights — **not**
  org-admin.

**Chosen execution-authorization approach: Solution A** (see §7): the runtime /
control-plane recognize the `service_agent` role for the *"run an evaluation"*
action, **scoped to the team carried in the request**. Agreed as the direction,
**subject to security review**.

---

## 2. Context

Evaluation has two phases with different presence of the end user:

| Phase | Component | User present? | Identity used |
| --- | --- | --- | --- |
| Create dataset / campaign, capture history | **Fapi** | yes (interactive) | **propagated user JWT** |
| Start a campaign (e.g. 3 days later) | **Fworker** | no | **own service identity** |

Fapi can authorize as the real user (scoped, RGPD-safe). Fworker cannot — the user
is gone — so it needs a service identity. The current shortcut (giving the service
the Keycloak `admin` role) is over-privileged and is the debt this RFC removes.

---

## 3. Principle

- **Fapi (synchronous):** propagate the **user JWT**. The runtime/control-plane
  authorize the **real user** (ReBAC on their teams). Scoped, RGPD-safe. No service
  identity needed for these operations.
- **Fworker (asynchronous):** use its **own service identity**. **Legitimacy is
  anchored at creation time** (the campaign was created by a user authorized on the
  team). **Authorization at execution is re-evaluated at time T** against the current
  state, via the service's **own (scoped)** rights — never a frozen user identity.

---

## 4. How Fworker is identified

**Fworker = a dedicated Keycloak service account.**

- At runtime, Fworker authenticates to **Keycloak** via **client_credentials** (M2M)
  using a **dedicated Keycloak client** (e.g. `fred-evaluation-worker`).
- Keycloak returns a **service JWT** whose `azp`/`client_id` = `fred-evaluation-worker`
  and `sub` = `service-account-fred-evaluation-worker`.
- That subject is the **principal** authenticated by the control-plane and runtime,
  and used in ReBAC authorization.

> **Identification = Fworker's dedicated Keycloak client (its `client_id` and service
> account subject).** It is the stable "who" of Fworker, independent of any user.

Fworker has its **own** client, distinct from any identity used by Fapi, so it can be
granted **specific, minimal** rights and its secret isolated.

---

## 5. Precedent in the codebase — the control-plane purge worker

The control-plane already runs an asynchronous worker that deletes conversation
history after a member is removed from a team. Its pattern (verified in
`scheduler/lifecycle_actions.py`):

```
1. Member removed from a team   → an event is ENQUEUED (purge_queue, MEMBER_REMOVED)
2. Later, the worker reads due items
3. It deletes directly: session_store.delete(session_id) + queue_store.mark_done(...)
```

Key properties: **no user token, no per-execution ReBAC** — legitimacy is **anchored
upstream** (the authorized membership change enqueues the event); the worker **trusts
the queue** and executes via **direct store access**.

**Lesson:** the platform already uses *"anchor legitimacy at the authorized moment,
the worker executes the already-legitimate work later."* This RFC reuses that
philosophy: the campaign created by an authorized user is the anchored-legitimate
work; Fworker executes it later.

**Difference:** the purge worker deletes **directly** (its own store), so it needs no
external auth. **Fworker must call the runtime** (an authenticated, ReBAC-gated
service) to execute the agent — so Fworker **does** need a service identity with
rights (unlike the purge worker).

---

## 6. Roles available today

- Predefined `app` client roles: **`admin`, `editor`, `viewer`, `service_agent`**.
- `service_agent` is the **existing service-to-service role** held by all other
  backend service accounts (`agentic`, `knowledge-flow`, `control-plane`).
- ReBAC converts only `admin`/`editor`/`viewer` into an org-level relation
  (`user_role_to_organization_relation`); **`service_agent` is NOT mapped** today, so
  a service holding only `service_agent` would currently **fail** the team ReBAC
  check. This is why `admin` had been used as a shortcut — and exactly the gap
  Solution A closes.

---

## 7. Decision — Solution A (chosen, pending security review)

Give Fworker the existing **`service_agent`** role (not `admin`), and **extend the
authorization layer** (runtime, control-plane, **and knowledge-flow**) so that a
`service_agent` is allowed to perform the **"run an evaluation"** action **scoped to the
`team_id` carried in the request** — i.e. the team of the legitimately-created campaign.

- Least privilege: Fworker can only **run evaluations**, and only **for the team in
  the request** — not org-wide admin, not arbitrary actions.
- Consistent with the platform's existing service identity (`service_agent`).
- No per-team OpenFGA tuple provisioning (avoids heavy dynamic provisioning).

### Exact permission the worker needs (least privilege)

The worker only **reads** the team and **writes results to its own DB**. It never
creates campaigns (that is the API) nor modifies team resources. Mapped per level:

| Layer | Grant | Why |
| --- | --- | --- |
| **Keycloak** | `service_agent` | service identity marker (no ReBAC power by itself) |
| **ReBAC — org** | **none** | the worker does not create agents (`editor`) or teams (`admin`) |
| **ReBAC — team** | **`can_read` only** | prepare-execution and execute are both gated by `can_read` |
| **ReBAC — team corpus (knowledge-flow)** | **read on the team's tags/libraries + documents** | a RAG agent run by the worker calls knowledge-flow vector search, which authorizes libraries/documents by ReBAC on the caller; without team-scoped read the corpus search is skipped and every RAG case retrieves nothing (discovered in end-to-end testing) |
| **ReBAC — resource (agent)** | **none** | executing an agent is gated by the team's `can_read`, not by an agent-level relation |

So Solution A grants `service_agent` the **team `can_read` level, scoped to the request
`team_id`** — nothing at org level, nothing at resource level, and no write on the team
(results are written to the evaluator's own DB, which is not ReBAC-gated).

> **Note — `can_read_conversations` is deliberately NOT granted.** Reading conversation
> history belongs to the **capture** phase, which is **synchronous (Fapi)** and runs
> under the **user's own JWT** (the user is a team member, so already holds
> `can_read_conversations`). The async worker never calls the history endpoint — its
> execution path is only `prepare-execution` + `evaluate`, both gated by `can_read`.
> Verified in `fred-evaluation-backend/.../execution/` (no history client on the worker
> path). Granting only `can_read` keeps the worker at the tightest least-privilege.

### Alternatives considered

- **Current — service `admin`:** works but over-privileged (access to ALL teams; if
  the secret leaks, full-platform compromise). Rejected as the target; tolerated only
  transitionally.
- **C-static — per-team OpenFGA relation** (`service:fworker → can_evaluate → team:X`):
  finest scoping, but requires dynamic provisioning of a relation per team/campaign.
  Heavier; not chosen.
- **D — delegation / on-behalf-of the user for deferred execution:** **rejected** for
  the asynchronous case, for fundamental security reasons (not merely token expiry):
  - it would require **storing a long-lived user credential** (anti-pattern, prime
    leak target);
  - it would act on **stale permissions** (the user's rights may have changed; no
    re-evaluation at time T);
  - it **falsifies audit/consent** ("the user acted" when they did not);
  - it introduces a dangerous **impersonation** capability (compromised service =
    become any user).
  - (D remains valid only for the **synchronous** case — the capture — where the user
    is present.)

---

## 8. What must be provisioned at platform installation

1. **Keycloak — Fworker identity**
   - A confidential client `fred-evaluation-worker` in realm `app`, with **service
     accounts enabled** (client_credentials).
   - Its **secret**, delivered to Fworker via env var (e.g. `KEYCLOAK_EVAL_WORKER_SECRET`).
   - Assign the **`service_agent`** role — **NOT `admin`**.

2. **Authorization layer (runtime + control-plane + knowledge-flow) — Solution A**
   - Recognize a `service_agent` caller as authorized for the **"run an evaluation"**
     action, **scoped to the request's `team_id`** (the campaign's team).
   - Enforcement points (defense in depth):
     - **control-plane** — `prepare-execution` (team `can_read`).
     - **runtime** — `execute`/`evaluate` (team `can_read`).
     - **knowledge-flow** — vector search / corpus read: recognize `service_agent`
       for **team-scoped read of the team's tags/libraries** (the corpus-scoping path),
       so a RAG agent run by the worker can retrieve the team's indexed corpus. Without
       this, the caller identity (`service_agent`) propagates from worker → runtime →
       knowledge-flow, resolves to **zero authorized libraries**, and every RAG case
       returns "nothing found in corpus". Read-only, scoped to `team_id` (no cross-team
       leak). **Implemented** in `TagService.resolve_authorized_tag_ids_in_rebac`
       (`apps/knowledge-flow-backend/.../features/tag/tag_service.py`, fred PR #1923):
       when `is_service_agent(user)`, the per-user READ baseline (empty for a service
       identity) is bypassed and the **team's** owner/editor/viewer tags are authorized
       directly, scoped to the request `team_id`; fail-closed (empty set) with no team
       or a personal team.
       > **Scope note.** This covers the **corpus-scoping** path (`tag_ids`), which is
       > what corpus RAG search uses — chunks are filtered by `tag_ids` in the vector
       > index. The separate **explicit per-document** path
       > (`MetadataService.filter_readable_document_uids`, used only when a caller passes
       > explicit `document_uids`) is **not** widened for `service_agent`: the async
       > evaluation worker does corpus search and never passes explicit document UIDs.
       > If a future case needs explicit-document reads under a service identity, extend
       > that path the same way.

3. **Legitimacy anchoring**
   - The campaign records `created_by` and `team_id` at creation (created by a user
     authorized on that team). Execution trusts this anchored-legitimate record
     (mirroring the purge-queue precedent), while re-checking the service's own
     scoped rights at time T.

> **Provisioning checklist** (code enforcement done; deployment provisioning in `fred-deployment-factory`)
> - [x] Runtime: accept `service_agent` for `execute`/`evaluate`, scoped to `team_id` — `fred-runtime/.../agent_app.py` (`_authorize_execution_or_raise`), audited, fail-closed if no team
> - [x] Control-plane: accept `service_agent` for `prepare-execution` (team `can_read`), scoped to `team_id` — `control-plane/.../teams/service.py` (`_validate_team_and_check_permission`); write permissions fall through to normal ReBAC → denied
> - [x] Knowledge-flow: accept `service_agent` for team-scoped **corpus** read (tags/libraries), scoped to `team_id` — `knowledge-flow/.../features/tag/tag_service.py` (fred PR #1923); required for RAG evaluations
> - [x] `fred-core` shared predicate + allow-list: `is_service_agent()` and `SERVICE_AGENT_ALLOWED_TEAM_PERMISSIONS = {CAN_READ}`
> - [ ] Keycloak client `fred-evaluation-worker` (confidential, service accounts ON) + secret — **deployment (`fred-deployment-factory`)**
> - [ ] Role `service_agent` on that client — **never** `admin`; the role must **never** be assignable to end users or public clients (see security boundary below)
> - [ ] Campaign record carries `created_by` + `team_id` (legitimacy anchor)
> - [ ] Audit: execution attributed to the service, referencing the campaign + `created_by`
>
> **Security boundary (deploy-time invariant).** Because a `service_agent` caller is
> authorized for the `team_id` **carried in the request** with **no OpenFGA tuple** binding
> the service to a team, any holder of a `service_agent` token can read **any** team's corpus
> by supplying that `team_id`. The entire trust boundary therefore collapses to *who can obtain
> a `service_agent` token*. The `service_agent` role MUST be granted **only** to trusted M2M
> service clients (`agentic`, `knowledge-flow`, `control-plane`, `fred-evaluation-worker`), never
> to a user, a public client, or a realm-default/composite role. Legitimacy of the specific team
> is anchored **upstream** at campaign creation (`created_by` + `team_id`), not re-checked here.

---

## 9. Invariants

- Fapi never uses a service identity for interactive operations → always the
  **propagated user JWT** (scoped).
- Fworker never impersonates a user → **service identity only**.
- Execution authorization is **re-evaluated at time T** against current state (not a
  creation-time snapshot).
- Fworker holds **only** the rights it needs, **scoped** to the relevant team — never
  org-admin.
- Audit attributes execution to the **service**, referencing the campaign and its
  `created_by`.

---

## 10. Open points (for the security review)

- Confirm that `service_agent` + per-request `team_id` scoping is acceptable, or
  whether a finer per-team relation (C-static) is required for classified profiles.
- Exact enforcement shape in the runtime/control-plane authorization layer
  (recognize `service_agent` for the action vs. add it to the role→ReBAC mapping with
  a limited permission).
- Whether Fapi needs any M2M client at all, or remains 100% user-JWT propagation.
- Secret lifecycle/rotation for the `fred-evaluation-worker` client.

---

## 11. Generalization — the service-account pattern for agent workers

**This is a deliberate architecture choice, not an evaluator-specific hack.** Any
**asynchronous agent worker** — a component that runs agents *without a user present*
(evaluation campaigns today; scheduled/batch agent runs, agent-to-agent pipelines, and
autonomous background workers tomorrow) — faces the same identity problem: it cannot
propagate a user JWT because no user is present, and it must not hold `admin` because
that is org-wide and turns a leaked secret into a full-platform compromise.

The pattern this RFC establishes, and which **future agent workers reuse verbatim**:

1. **One identity per worker** — a confidential Keycloak client with **service accounts
   enabled**, holding the **`service_agent`** role and **nothing stronger**. Never `admin`.
2. **`service_agent` is an identity marker, not a ReBAC power** — no OpenFGA tuple is
   stored for it. Each enforcement point recognizes it explicitly and grants **only**
   the least-privilege action it guards, **scoped to the `team_id` in the request**.
3. **Read-only by construction** — the shared allow-list
   `SERVICE_AGENT_ALLOWED_TEAM_PERMISSIONS = {CAN_READ}` is the single source of truth;
   any write permission falls through to the normal ReBAC check and is therefore denied.
   A new worker that needs a different action extends this allow-list *intentionally and
   reviewably* — it does not fork the predicate.
4. **Legitimacy anchored upstream** — the enforcement points trust the `team_id` in the
   request; the *right* to act on that team is established at the moment the work was
   created by an authorized user (here: campaign `created_by` + `team_id`), mirroring the
   RGPD purge-queue precedent. Rights are re-evaluated at execution time T against current
   state, never from a creation-time snapshot.
5. **Defense in depth across services** — the same predicate (`is_service_agent`) is
   enforced independently at **every** service the worker calls (runtime, control-plane,
   knowledge-flow). Adding a worker that reaches a new backend means adding the same
   scoped, read-only, fail-closed recognition at that backend's enforcement point — using
   the shared `fred-core` helpers, not a parallel implementation.

**Consequence for the platform.** The security posture of *every* agent worker reduces to
the single deploy-time invariant stated in §8: **strictly control which clients hold the
`service_agent` role.** Get that right once, and each new worker inherits a proven,
least-privilege, team-scoped, read-only identity model with no new authorization surface to
design. `fred-agent-evaluator` (a campaign of questions that drives agents and produces a
DeepEval KPI report) is the **first** consumer of this pattern; it is intended to be the
template for the ones that follow.
