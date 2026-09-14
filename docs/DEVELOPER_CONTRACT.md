# Developer Contract — fred-agent-evaluator

## Règles fondamentales

1. **Le frontend ne soumet jamais d'URL** — seulement des identifiants (`runtime_id`, `agent_instance_id`). Les URLs sont résolues par le Control Plane.
2. **L'API ne score jamais** — DeepEval est une dépendance du worker uniquement (`[scoring]`).
3. **Le worker n'expose pas d'HTTP** — il accède directement à la DB.
4. **Chaque cas est persisté indépendamment** — un crash du worker ne doit pas effacer les résultats déjà calculés.
5. **`fred-deepeval-cli` est la seule dépendance locale** — `fred-core` et `fred-sdk` viennent de PyPI.
6. **L'API et le worker n'utilisent jamais la même identité sortante** (RFC `EVAL-AUTH`, issue #33) — voir §Identity below.

## Identity: API-user vs worker-service (RFC `EVAL-AUTH`)

Every outbound call to the Control Plane passes an explicit `OutboundAuth`
(`execution/outbound_auth.py`) — there is no default, so no call site can
silently pick the wrong identity:

| Component | Identity used | `OutboundAuth` variant |
|---|---|---|
| API (`main.py`, interactive `POST /evaluations`, `POST /evaluations/{id}/runs`) | the caller's own bearer token, propagated verbatim | `UserAuthentication` (security enabled) / `NoAuthentication` (local dev, security disabled) |
| Worker (`main_worker.py`, Temporal activities and the in-memory `CampaignRunner`) | the worker's own M2M service identity (`fred-evaluation-worker` Keycloak client) | `ServiceAuthentication` |

Rules this enforces:

- `main.py` never builds an M2M token provider — the API's `ControlPlaneClient` has none, so a call that (by mistake) requested `ServiceAuthentication` fails fast with `RuntimeError` instead of silently sending an unauthenticated or wrong-identity request.
- The user's bearer token is **request-scoped only**. It lives in the `UserAuthentication` value passed to a single call — never on `ControlPlaneClient` (which only holds connection config + the worker's M2M provider), never in Temporal (`RunInput` carries only `run_id`), never in the `evaluation_run` table (which stores `created_by` + `team_id`, not a credential).
- A missing/malformed `Authorization` header fails closed with 401. That check is fred-core's own `get_current_user` dependency (resolved before any route body runs) — the evaluator normalizes its unstructured error into its own envelope (see below). With security disabled (local dev), the API explicitly uses `NoAuthentication` rather than falling back to the worker's M2M identity.

## Stable error codes and the one public envelope

`execution/evaluator_errors.py` is the evaluator API's one error contract. It:

1. classifies **known Control Plane boundary failures** (`httpx.HTTPStatusError`,
   timeout/transport errors, and the dedicated `ControlPlaneInvalidResponseError`
   for a malformed 2xx body — see `execution/control_plane_client.py`) instead of
   returning a blanket 422. A local/programming/configuration defect (e.g.
   `RuntimeError`) is *not* caught here and propagates as a real server error;
2. normalizes fred-core's own unstructured 401/403 `HTTPException`s (e.g. `{"detail":
   "No authentication token provided"}`) into the same envelope. fred-core's
   `get_current_user` dependency runs before any route body, so the evaluator's
   own resolvers never see that failure — `main.py` registers
   `normalize_unstructured_auth_error` as the app's `HTTPException` handler to
   close that gap at the API boundary. It never touches an already-structured
   evaluator error (dict `detail`), never touches fred-core's own decisions, and
   preserves response headers (e.g. `WWW-Authenticate`).

The one public envelope is `EvaluatorErrorResponse`, documented in OpenAPI for
every status below:

```json
{"detail": {"code": "target_forbidden", "message": "..."}}
```

The vocabulary is target-neutral — the resolver serves both `runtime_agent`
and `managed_instance`, so codes describe the failure, not the target kind:

| Condition | HTTP status | `code` |
|---|---|---|
| Missing/malformed `Authorization` header (fred-core, normalized) | 401 | `authentication_required` |
| Any other unstructured 403 from an auth dependency (fred-core, normalized) | 403 | `access_forbidden` |
| Control Plane 401 | 401 | `control_plane_authentication_failed` |
| Control Plane 403 | 403 | `target_forbidden` |
| Control Plane 404 | 404 | `target_not_found` |
| Control Plane 409 | 409 | `target_unavailable` |
| Control Plane 422 | 422 | `target_invalid` (see note below) |
| Control Plane 5xx / timeout / connection failure | 503 | `control_plane_unavailable` |
| Malformed/unexpected 2xx upstream response | 502 | `control_plane_invalid_response` |

Note: the creation routes themselves can also return 422 for FastAPI's own request-body
validation (malformed JSON payload) — a different body (`HTTPValidationError`).
Both are documented on the same status via an OpenAPI `oneOf`.

`message` is safe and actionable (never the raw target UUID); technical
context (operation, `team_id`, target id, category) is logged server-side —
never a bearer token or full `Authorization` header.

## API contract

Base URL : `/evaluation/v1`

**Deux ressources, deux rôles** — `evaluation` (la définition) et `run` (une
exécution). Une **evaluation** est immuable : elle porte le nom, la version et
les cas, créée une fois (upload JSON ou saisie manuelle), jamais éditée en
place. Un **run** l'exécute contre une cible ; ré-exécuter crée un nouveau run
sans écraser les résultats précédents. Il n'existe pas de payload `cases` en
ligne à la création d'un run — les cas viennent toujours de l'evaluation.

| Méthode | Route | Status | Description |
|---|---|---|---|
| POST | `/evaluations` | 201 | Créer une evaluation immuable — `{team_id, name, cases}` requis, `{version, author, source_filename}` optionnels (`origin: upload \| manual`, 1 à 200 cas). Version déclarée = identité (409 si doublon) ; sinon assignée par le serveur. 409 aussi si `(team, name, version)` existe déjà. |
| DELETE | `/evaluations/{id}` | 204 | Supprimer une evaluation **et tous ses runs** (cas, métriques, events). Refusé en 409 si un run est en cours. |
| GET | `/evaluations` | 200 | Lister (param: `team_id`) — id, nom, version, auteur, origin, complétude, nombre de cas, `created_at` |
| POST | `/evaluations/{id}/runs` | 202 | Démarrer un run — `{team_id, target, metrics, custom_metrics, agent_model_override}` (`extra: forbid`). Cible **`managed_instance` uniquement** (`runtime_agent` retiré de la création, conservé en lecture pour l'historique). `metrics` (obligatoire, non vide) est la sélection manuelle des métriques DeepEval à calculer ; `custom_metrics` (optionnel) porte les critères GEval. `agent_model_override` (optionnel) force le modèle de chat de l'agent cible pour ce run uniquement — jamais persisté côté Control Plane, jamais l'équivalent de la politique de routage d'équipe. Judge et concurrence restent fixés côté serveur et figés dans un `RunSnapshot`. |
| GET | `/evaluations/{id}/runs` | 200 | Lister les runs d'une evaluation (paginé, `offset`/`limit`/`sort`) |
| GET | `/evaluations/{id}/runs/summary` | 200 | Agrégats sur *tous* les runs de l'evaluation (running/completed/cases/erreurs critiques) — indépendant de la pagination, pour les KPI du dashboard |
| GET | `/runs/{run_id}` | 200 | Détail d'un run + agrégats |
| GET | `/runs/{run_id}/cases` | 200 | Cas paginés |
| GET | `/runs/{run_id}/cases/{case_id}` | 200 | Détail d'un cas |
| GET | `/runs/{run_id}/events` | 200 | SSE temps réel |
| GET | `/runs/{run_id}/report` | 200 | Rapport JSON complet et autoportant d'un run — archivage / LLM-as-judge |
| POST | `/runs/{run_id}/cancel` | 202 | Annuler |
| DELETE | `/runs/{run_id}` | 204 | Supprimer (refusé si `operational_state == running`) |
| POST | `/runs/{run_id}/analyze` | 200 | Analyse LLM du résultat, mise en cache |
| GET | `/telemetry` | 200 | Config Langfuse (activé/désactivé) |
| GET | `/telemetry/session/{run_id}` | 200 | Lien de session Langfuse si disponible |

Le suivi de tâche asynchrone est exposé séparément : `GET /tasks`,
`GET /tasks/{id}`, `GET /tasks/{id}/latest`, `GET /tasks/{id}/events` (SSE) et
`POST /tasks/{id}/cancel`.

Il n'existe pas de `GET /evaluations/{id}` ce cycle — la liste transporte déjà
tout ce dont l'écran de sélection a besoin, et le démarrage d'un run charge les
cas de l'evaluation côté serveur (pas via l'API publique).

Ce cycle **(EVAL-04, première version)** ne couvre que les runs sur agent managé
(`managed_instance`). Sont volontairement différés : cible `runtime_agent` à la
création, sélection du profil judge, réglages de concurrence/timeout, CSV, et
un écran de gestion des evaluations indépendant du démarrage d'un run.

## Metric selection (manual — replaces automatic profile detection for metrics)

`StartRunRequest.metrics: list[str]` is the caller's explicit, non-empty
selection of built-in DeepEval metrics — no automatic detection. Allowed ids
live in `runs/metrics_catalog.py` (API layer, zero `deepeval` dependency):
`answer_relevancy`, `faithfulness`, `contextual_relevancy`,
`contextual_precision`, `contextual_recall`. `contextual_precision` /
`contextual_recall` selected on a case with no `expected_output` are reported
with verdict `"skipped"` rather than erroring.

## Agent model override + traceability (run-scoped, no operation dimension)

`StartRunRequest.agent_model_override: str | None` forces the target agent's
chat model for this run only. It is threaded, unvalidated on this side, to the
Control Plane's `prepare-execution` as a query param — the Control Plane is
the sole authority on whether the profile is `can_use`-enabled for the team,
and rejects (422) if not. Never persisted by the Control Plane, never visible
in the team's routing policy. No per-operation variant — see `fred`'s own
model-routing simplification (2026-08-17) for why that dimension was dropped
there first.

**Not validated eagerly at run creation.** `start_run`'s `resolve_managed_instance`
call authenticates as the interactive caller (`resolve_interactive_auth`), but
the Control Plane only honors `agent_model_override` for the worker's service
identity (`ServiceAuthentication`) — forwarding it on that call would 403
every override unconditionally, before the run even starts (found live,
2026-09-14). The override is validated for real only at case execution time,
by the worker (`workers/workflow.py` / `workers/runner.py`, both
service-authenticated); an invalid override surfaces as that case's execution
error, not a run-creation failure.

Both execution engines read `EvaluationRunRow.agent_model_override` directly
and forward it to `prepare_managed_instance_execution` — `workers/workflow.py`
(Temporal) and `workers/runner.py` (polling). Keep them in sync; nothing
enforces it structurally.

`EvaluationCaseResponse.actual_model_name` is ground truth, not an echo of the
request: it is `EvalTrace.model_name`, read from the LLM provider's own
response metadata by the runtime pod. It can differ from
`EvaluationRun.agent_model_override` if a higher-precedence Control Plane
policy (platform binding, pod static override) silently won — compare the two
rather than trusting the override was honored. `GET /runs/{run_id}/report`
surfaces both.

`StartRunRequest.custom_metrics: list[CustomMetricSpecInput]` carries
GEval-scored, user-authored criteria (`name`, `criteria`, `parameters`,
`threshold`). It only validates shape — not whether `parameters` names are
valid `LLMTestCaseParams` members, because that check imports `deepeval`,
which the API image never installs (`dockerfiles/Dockerfile-api`). The
stricter check happens worker-side (`fred_deepeval_cli.core.models.CustomMetricSpec`),
so an unknown parameter name surfaces as a per-case scoring error, not a
run-creation error.

Both fields are persisted verbatim (`metrics_json`, `custom_metrics_json` on
`EvaluationRunRow`) and read back by the worker (Temporal `workflow.py` and
the in-memory `runner.py`) to build the metric list passed to
`fred_deepeval_cli.core.scorer.score_trace(metrics=..., custom_metrics=...)`.

They are also echoed back on `EvaluationRun` (`GET /evaluations/{id}/runs`,
`GET /runs/{run_id}`) as `metrics: list[str]` / `custom_metrics: list[CustomMetricSpecInput]`,
so a caller — e.g. the frontend's rerun — can read back which metrics a given
run was scored against instead of guessing a default.

## Scoring profiles (structural checks only)

`resolve_profile()` (`fred-deepeval-cli`) still runs automatically — but now
only feeds `build_structural_checks` (the non-LLM SQL/RAG/workflow checks),
never the metric list above:

- `"auto"` — détection automatique RAG/SQL/workflow via `resolve_profile()` dans fred-deepeval-cli
- RAG détecté si `"rag"` figure dans `agent_tags` de l'EvalTrace

## Format dataset JSON

Le document est **auto-descriptif** : il porte son identité et sa provenance, pour
qu'une copie archivée reste lisible sans la requête qui l'a déposée. 1 à 200 cas.

```json
{
  "name": "golden-set",
  "version": "1.0.0",
  "author": "Équipe Data",
  "cases": [
    {
      "input": "Question posée à l'agent",
      "expected_output": "Réponse attendue (optionnel, requis pour ContextualPrecision/Recall)"
    }
  ]
}
```

- `name` — requis.
- `version` — optionnelle. **Déclarée, elle fait autorité** et `(team, name, version)`
  devient l'identité : redéposer la même version renvoie 409. Omise, le serveur
  assigne `v1`, `v2`… Une version déclarée non numérique ne perturbe pas cette suite.
- `author` — optionnel, texte libre, purement **déclaratif**. L'uploadeur authentifié
  est enregistré séparément dans `created_by` et ne peut pas être usurpé par le document.

`external_id` et `tags` restent acceptés (voir `EvaluationCase`) mais ne sont
pas requis. Pas de CSV. Une evaluation créée manuellement (`origin: "manual"`)
suit la même forme `EvaluationCase`, saisie ligne par ligne côté UI.

`completeness` est **dérivée** des cas, jamais acceptée en entrée : `complete`
seulement si tous les cas ont un `expected_output`, `minimal` sinon. Guide
analyste : [`guide/write-a-dataset.md`](guide/write-a-dataset.md).

## Commandes développeur

```bash
# Qualité de code
make code-quality
make code-quality-fix

# Tests
make test

# Local dev
cd apps/fred-evaluation-backend
make run          # API sur :8333
make run-worker   # Worker
```
