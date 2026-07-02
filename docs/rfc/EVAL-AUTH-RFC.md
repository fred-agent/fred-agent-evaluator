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
authorization layer** (runtime + control-plane) so that a `service_agent` is allowed
to perform the **"run an evaluation"** action **scoped to the `team_id` carried in the
request** — i.e. the team of the legitimately-created campaign.

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
| **ReBAC — team** | **`can_read` only** | prepare-execution and execute are both gated by `can_read`; that is all the async worker calls |
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

2. **Authorization layer (runtime + control-plane) — Solution A**
   - Recognize a `service_agent` caller as authorized for the **"run an evaluation"**
     action, **scoped to the request's `team_id`** (the campaign's team).
   - Keep the runtime and control-plane as the **enforcement points** (defense in depth).

3. **Legitimacy anchoring**
   - The campaign records `created_by` and `team_id` at creation (created by a user
     authorized on that team). Execution trusts this anchored-legitimate record
     (mirroring the purge-queue precedent), while re-checking the service's own
     scoped rights at time T.

> **Provisioning checklist**
> - [ ] Keycloak client `fred-evaluation-worker` (confidential, service accounts ON) + secret
> - [ ] Role `service_agent` on that client — **never** `admin`
> - [ ] Runtime + control-plane: accept `service_agent` for the evaluation action, scoped to `team_id`
> - [ ] Campaign record carries `created_by` + `team_id` (legitimacy anchor)
> - [ ] Audit: execution attributed to the service, referencing the campaign + `created_by`

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
