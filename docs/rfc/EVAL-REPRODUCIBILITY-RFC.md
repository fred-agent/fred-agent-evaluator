# RFC EVAL-REPRO — Reproducibility, traceability and export of an evaluation

**Status:** draft for discussion
**Author:** Odelia Cohen
**Reviewers:** Dimitri Tombroff, Laurence Guillon, Thomas
**Track:** `EVAL-REPRO`
**Related:** `EVAL-DATASET-RFC.md` (dataset entity, immutability),
`EVAL-CUSTOM-METRIC-RFC.md`, control-plane `MIGR-05` (snapshot exporter),
`MIGR-06` (object-store mirroring)

---

## 1. Decision requested

Agree that an evaluation campaign must record **what was evaluated**, not merely a label
for it — the agent's *effective* configuration, the dataset, and the state of the
knowledge base — and that a team can **export a self-contained bundle** of a campaign for
audit and reproduction.

Concretely, agree on: (a) which fields identify each part, given that an agent's behaviour
comes from **four distinct sources** (§3.2); (b) that each part is stored as
*content + fingerprint*; (c) the phasing (§8); (d) the RGPD stance (§5).

---

## 2. Problem

A campaign stores **labels, not evidence**.

- The agent is stored as `agent_instance_id`. Rename it → the history changes; delete it →
  the view breaks; change its prompt, model, or RAG scope → nothing records it.
- The dataset is two free-text strings (`dataset_name`, `dataset_version`) typed by the
  user. Two campaigns labelled `rag v1` may hold different cases. The dataset is dissolved
  into `evaluation_case` rows, one copy per campaign.
- The knowledge base is not recorded at all.

Consequence: two campaigns cannot be compared. A score change cannot be attributed — the
agent, the questions, or the documents? Nothing tells us.

---

## 3. What already exists (verified in code)

Most primitives are present and unused. **Extend, do not reinvent.**

### 3.1 The dataset is a fully-designed two-model pipeline, merely unwired

The dataset domain (`EVAL-DATASET`) is far more built than the campaign path suggests.
Two models:

- **`QuestionSet`** — capture + curation. Carries *Laurence's triage exactly*: three
  criteria scored 1–5 (`is_relevant_question`, `is_rag_question`, `answerability`), a
  `keep_threshold` (default 4), Analytics-style filters (period, agent, session). It is
  **mutable** (has `updated_at`) because it is being curated.
- **`EvaluationDataset`** — the frozen dataset. It has **no `updated_at`**, and no code
  performs `update`/`delete` on it: **immutable by design and in fact.** Therefore
  `dataset_id` alone proves identity — no content hash needed. Immutability *is* the
  fingerprint, and this is now verified, not assumed.

Each `DatasetCase` carries provenance (`source_candidate_id`, `source_session_id`).
`completeness` (`minimal` = input only / `complete` = input + expected) is **derived from
the cases, never trusted as input** — this already answers the meeting's "run a campaign
with no expected output": the system distinguishes the two natively.

The table has **zero rows** — `create_campaign` never writes to it. This is the only gap:
wiring, not design.

### 3.2 An agent's behaviour comes from FOUR sources, not one

This is the central finding, and it corrects an earlier draft that captured only the first.

| # | Source | Holds | Scope | Exposed? |
| --- | --- | --- | --- | --- |
| 1 | `agent_instance.tuning_json` | **system prompt** (`values["prompts.system"]`), MCP server selection + config | per instance, in DB | **yes** |
| 2 | `RuntimeContext` (execution) | **RAG behaviour**: `search_policy` (strict/hybrid/semantic), `search_rag_scope` (corpus_only/hybrid/general_only), `selected_document_libraries_ids`, `deep_search`, `language` | per execution | **yes** |
| 3 | `models_catalog.yaml` | **LLM model + temperature** (`temperature: 0.0`) | deployment config | exists, **not per-instance** |
| 4 | `rag_expert.py` `ReActPolicy` | **guardrails** (`grounding`, `uncertainty`) | agent code | exists, **hard-coded** |

Two agents with the same prompt but different `search_rag_scope`, or different
`temperature`, behave differently. A fingerprint built from source 1 alone would call them
identical — the bug this section exists to prevent.

Note also on the prompt itself:

- The system prompt is stored **inline** in `tuning_json.values["prompts.system"]` — *not*
  referenced. `prompt_refs_json` is **`NULL`** on live rows and appears in no application
  code (only the ORM model, the MIGR-05 pass-through, and a dormant migration). Hashing
  `tuning_json` therefore captures prompt edits directly.
- **Blind spot:** when the override is blank, the agent uses the default prompt hard-coded
  in `fred-agents` — which changes with a deployment, not the DB (§9.1).

### 3.3 Documents DO have a content fingerprint, and an object store — reuse them

An earlier draft claimed documents had no content hash. **That was wrong** — two layers
were conflated.

- **Ingestion computes a content hash.** `base_input_processor._probe_file_info` streams
  the file in 1 MB chunks and computes both **`sha256` and `md5` of the content**, stored
  on the document metadata (`doc.sha256`, `doc.md5`). Code comment: *"hashes may be useful
  later (dedupe, integrity)"*. This is a genuine content fingerprint.
- The **path** hash I cited earlier belongs to a *different* layer — the pull/catalog scan
  that lists files (`filesystem_content_loader`, sometimes `"na"`) — not the ingestion
  metadata.
- **An object store already exists.** GCS / MinIO / local file stores persist each binary
  with a `gs://…`-style URI **and** a per-object `checksum_sha256` of the content. Dimitri's
  "GCS snapshot with an id" is therefore largely already in place: binaries live in object
  storage, addressed by URI, with content checksums.

So the document fingerprint is a field to **read**, not to invent. The remaining questions
are narrower (§9.4): is `doc.sha256` reliably populated and exposed to the evaluator, and
does per-campaign freezing still matter given content-addressed storage already exists?

### 3.4 A snapshot export format already exists (MIGR-05)

`control_plane_backend/import_export/exporter.py` produces a re-importable `.zip`
(`manifest.json` + `postgres/*.jsonl`); binaries and embeddings are *"mirrored separately
(MIGR-06)"*. The evaluation bundle reuses this shape.

---

## 4. Proposal

Governing rule, applied to every part:

> **Store the content, and store its fingerprint.** The fingerprint answers *"is it the
> same?"* — cheap, comparable, personal-data-free. The content answers *"what changed?"* —
> and only it can.

### 4.1 The dataset becomes a frozen entity, not dissolved cases (2-in-1 with EVAL-DATASET)

Today `create_campaign` dissolves the user's dataset directly into `evaluation_case` rows
and keeps two free-text labels on the campaign. The cases survive; the dataset's identity
does not. Two campaigns labelled `arxiv v1` may hold different questions.

This RFC and `EVAL-DATASET` converge here — one gesture serves both. At campaign creation:

1. freeze an `EvaluationDataset` (immutable, versioned) from what the user supplied, deriving
   `completeness` from the cases (the schema already does this);
2. the campaign references it by `dataset_id`;
3. `evaluation_case` rows are materialised from that dataset and remain the execution unit.

Two campaigns on the same `dataset_id` are then provably asking the same questions.

**Scope — RGPD-safe subset only.** Restrict to `origin = upload` (the user's `dataset.json`)
and `origin = manual` (typed in the form). These come straight from the user and touch no
personal history. `origin = capture` — building a dataset from conversation history via
`QuestionSet` — stays **out of scope**, paused on RGPD (Dimitri).

**Effort — write the wiring, not just plug it in.** `evaluation_dataset` (the ORM table)
and the Pydantic schemas exist, but the `datasets` module has **no store, no service, no
API** — nothing writes a row today. This step adds: a dataset store (insert-only, to preserve
immutability), the freeze call inside `create_campaign`, and a `dataset_id` column on the
campaign (+ migration). Moderate, comparable to EVAL-CUSTOM-METRIC. No dataset-management
UI or API is required.

### 4.2 The agent's EFFECTIVE configuration is snapshotted at campaign creation

Two columns, mirroring `custom_metrics_json`:
`agent_config_json` (Text) and `agent_config_hash` (String(64), indexed).

The dump gathers **all four behaviour sources** (§3.2), not just the prompt:

| In the fingerprint | From |
| --- | --- |
| `template_id`, `source_runtime_id`, `source_agent_id` | instance |
| `tuning_json` (prompt + MCP) | instance (source 1) |
| `search_policy`, `search_rag_scope`, `selected_document_libraries_ids`, `deep_search`, `language` | RuntimeContext (source 2) |
| model id + `temperature` | models_catalog (source 3) — **§9.2** |
| guardrail ids + agent image version | agent code (source 4) — **§9.1** |

**Out of the fingerprint** (labels, not behaviour): `display_name`, `description`, `tags`,
`enabled`, `created_by`, `created_at`, `updated_at`, tokens, correlation/trace ids.

**Canonicalisation mandatory** — sorted keys, no whitespace, fixed encoding:

```python
dump = json.dumps(behaviour, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
fingerprint = hashlib.sha256(dump.encode("utf-8")).hexdigest()
```

### 4.3 The knowledge-base state is recorded per document — mostly by reuse

The content hash already exists (`doc.sha256`, §3.3). At campaign creation the evaluator
records, per document in scope: `document_uid`, filename, `doc.sha256`, and the existing
object-store URI. Binaries are never inlined. This is largely wiring — confirm `doc.sha256`
is populated and reachable, rather than compute anything new (§9.4).

### 4.4 The evaluation bundle

Team-UI export of a campaign as a `.zip`, reusing the MIGR-05 shape:

```
manifest.json      bundle version, campaign id, created_at, per-part fingerprints
campaign.json      metadata, aggregates, verdict, generated analysis
cases.jsonl        per case: input, expected, actual, per-metric score/verdict/reason
dataset.json       dataset snapshot (id, name, version, cases)
agent_config.json  { "hash": ..., "config": <effective four-source dump> }
resources.json     documents: uid + filename + content_hash + storage_ref  (no binaries)
```

Each part carries **content + fingerprint**. After the retention window, contents are
purged and only fingerprints remain (§5).

---

## 5. RGPD

| Part | Personal data? | Retention |
| --- | --- | --- |
| Any fingerprint | **No** — a hash is irreversible | keep indefinitely |
| Agent dump | **Yes** — `tuning_json` holds the system prompt inline (§3.2) | window |
| Dataset | **Yes** — user questions | window |
| Document content hashes | **No** | keep indefinitely |
| Document binaries | Yes | window / object store |
| Campaign report | Contains agent answers | window |

Two RGPD facts to decide on:

1. **Purge contents, keep fingerprints.** After the window, erase prompt/questions/answers
   and binaries; retain hashes. The platform loses *what* changed, keeps *that* it changed.
   Traceability and erasure are reconciled.
2. **Export leaves the platform's control.** A downloaded `.zip` cannot be remotely erased.
   This is the bundle's sharpest risk — gate who may export, and consider a hash-only
   bundle mode for sharing outside the retention perimeter (§9.5).

---

## 6. Non-goals

- Re-running a campaign from a bundle (import). Export first.
- Replacing MIGR-05 / MIGR-06 — reuse their shape and object-store strategy.
- Question triage / capture (Laurence's `tri`) — separate track, blocked on RGPD.

---

## 7. Risks

| Risk | Mitigation |
| --- | --- |
| Fingerprint blind to model/temperature/RAG-scope changes | capture all four sources (§3.2, §4.2) — the core correction of this RFC |
| Fingerprint blind to a changed *default* prompt (blank override) | §9.1 — effective prompt or agent image version |
| Non-canonical serialisation → spurious drift | mandatory sorted-key canonical dump (§4.2) |
| Snapshot storage grows per campaign | content-addressed storage (§9.4) |
| Bundle exports personal data off-platform | §5.2 — gate export; hash-only mode |
| Dataset immutability not enforced | enforce at write, or add a dataset content hash (§9.3) |

---

## 8. Phasing

Each step is independently useful and shippable.

1. **Freeze the dataset** (§4.1). Write the dataset store + freeze in `create_campaign`,
   `origin` upload/manual only. 2-in-1 with EVAL-DATASET; `capture`/`QuestionSet` stays paused.
2. **Agent effective-config fingerprint** (§4.2). Start with sources 1–2 (already exposed);
   add sources 3–4 once §9.1/§9.2 are decided.
3. **Document scope + content hash** (§4.3). Reuse `doc.sha256` and the object-store URI;
   confirm they are populated and reachable. Lighter than first thought.
4. **Bundle export** (§4.4). Assembles steps 1–3.

---

## 9. Open questions

1. **Guardrails and the default prompt live in agent code, not the DB.** *(blocking §4.2)*
   A `fred-agents` release can change the built-in prompt or the guardrails with no DB
   change, so two campaigns can share a fingerprint yet differ. Options: fingerprint the
   *effective* prompt/guardrails resolved at execution; or include the `fred-agents` image
   version in the fingerprint; or accept and document the blind spot.
2. **Model and temperature live in `models_catalog.yaml` (deployment), not per-instance.**
   They fully determine behaviour but are not evaluation-time data today. Does the runtime
   expose the resolved model + temperature per execution, so the evaluator can capture
   them? If not, is exposing them worth a contract change? *(This is the "interesting
   fields Fred has but does not yet expose" question.)*
3. ~~Is dataset immutability enforced?~~ **Resolved (§3.1):** `EvaluationDataset` has no
   `updated_at` and no update/delete path — immutable in fact. `dataset_id` proves identity.
4. **Is `doc.sha256` reliably populated, and exposed to the evaluator?** It is computed at
   ingestion (§3.3) but may be absent on documents ingested before that path, or via loaders
   that skip it. And the evaluator reaches documents through the control-plane / knowledge-
   flow API — does that surface `doc.sha256`? Also: given the object store already content-
   addresses binaries, is a *separate* per-campaign snapshot needed, or does recording the
   existing URI + sha256 suffice? (If binaries can be deleted/replaced in place, a freeze is
   still needed; if the store is append-only, the URI is already stable.)
5. Who may export, and is a hash-only bundle mode needed for off-platform sharing (§5.2)?

---

## 10. Acceptance criteria

- A campaign references a `dataset_id`; two campaigns on the same dataset are provably
  asking the same questions.
- A campaign stores `agent_config_json` + `agent_config_hash` covering the effective
  configuration; renaming the agent leaves the hash unchanged, while changing its prompt,
  RAG scope, or (once §9.2 lands) its temperature changes it.
- Documents carry a content hash; two campaigns can be diffed to which files changed.
- A team can export a bundle whose `manifest.json` lists each part's fingerprint and which
  contains no object-store binaries.
- Purging contents after the retention window leaves every fingerprint intact.
