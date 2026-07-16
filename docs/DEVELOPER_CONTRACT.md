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
| API (`main.py`, interactive `POST /campaigns`) | the caller's own bearer token, propagated verbatim | `UserAuthentication` (security enabled) / `NoAuthentication` (local dev, security disabled) |
| Worker (`main_worker.py`, Temporal activities and the in-memory `CampaignRunner`) | the worker's own M2M service identity (`fred-evaluation-worker` Keycloak client) | `ServiceAuthentication` |

Rules this enforces:

- `main.py` never builds an M2M token provider — the API's `ControlPlaneClient` has none, so a call that (by mistake) requested `ServiceAuthentication` fails fast with `RuntimeError` instead of silently sending an unauthenticated or wrong-identity request.
- The user's bearer token is **request-scoped only**. It lives in the `UserAuthentication` value passed to a single call — never on `ControlPlaneClient` (which only holds connection config + the worker's M2M provider), never in Temporal (`CampaignInput` carries only `campaign_id`), never in the `evaluation_campaign` table (which stores `created_by` + `team_id`, not a credential).
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

Note: `POST /campaigns` itself can also return 422 for FastAPI's own request-body
validation (malformed JSON payload) — a different body (`HTTPValidationError`).
Both are documented on the same status via an OpenAPI `oneOf`.

`message` is safe and actionable (never the raw target UUID); technical
context (operation, `team_id`, target id, category) is logged server-side —
never a bearer token or full `Authorization` header.

## API contract

Base URL : `/evaluation/v1`

**Datasets are first-class, immutable resources** (`EVAL-04`, 2026-07-16). A
dataset is created once (JSON upload or manual rows), never edited in place,
and referenced by campaigns via `dataset_id`. Campaigns no longer accept an
inline `dataset`/`cases` payload — that path was removed, not deprecated.

| Méthode | Route | Status | Description |
|---|---|---|---|
| POST | `/datasets` | 201 | Créer un dataset immuable (`origin: upload \| manual`); nom et version assignés par le serveur |
| GET | `/datasets` | 200 | Lister (param: `team_id`) — id, nom, version, origin, complétude, nombre de cas, `created_at` |
| POST | `/campaigns` | 202 | Créer une campagne — `{team_id, target, dataset_id}` uniquement. Cible **managed_instance uniquement** ce cycle (`runtime_agent` retiré de la création, conservé en lecture pour l'historique). Nom, profil, judge, métriques et concurrence sont fixés côté serveur. |
| GET | `/campaigns` | 200 | Lister (param: `team_id`) |
| GET | `/campaigns/{id}` | 200 | Détail + agrégats + résumé du dataset référencé |
| GET | `/campaigns/{id}/cases` | 200 | Cas paginés (max 200) |
| GET | `/campaigns/{id}/cases/{case_id}` | 200 | Détail d'un cas |
| GET | `/campaigns/{id}/events` | 200 | SSE temps réel |
| POST | `/campaigns/{id}/cancel` | 202 | Annuler |
| DELETE | `/campaigns/{id}` | 204 | Supprimer (refusé si `operational_state == running`) |
| POST | `/campaigns/{id}/analyze` | 200 | Analyse LLM du résultat, mise en cache |
| GET | `/telemetry` | 200 | Config Langfuse (activé/désactivé) |
| GET | `/telemetry/session/{campaign_id}` | 200 | Lien de session Langfuse si disponible |

Il n'existe pas de `GET /datasets/{id}` ce cycle — la liste transporte déjà
tout ce dont l'écran de sélection a besoin, et la création de campagne charge
les cas du dataset côté serveur (pas via l'API publique).

Ce cycle **(EVAL-04, première version)** ne couvre que les campagnes sur agent
managé (`managed_instance`). Sont volontairement différés : cible
`runtime_agent` à la création, métriques personnalisées, sélection du profil
judge, réglages de concurrence/timeout, CSV, et un écran de gestion des
datasets indépendant de la création de campagne.

## Scoring profiles

- `"auto"` — détection automatique RAG vs non-RAG via `resolve_profile()` dans fred-deepeval-cli
- RAG détecté si `retrieval_context` non vide dans l'EvalTrace
- `ContextualPrecision` et `ContextualRecall` nécessitent `expected_output` dans le cas

## Format dataset JSON

Format strict, unique, utilisé par `POST /datasets` (`origin: "upload"`) :

```json
[
  {
    "input": "Question posée à l'agent",
    "expected_output": "Réponse attendue (optionnel, requis pour ContextualPrecision/Recall)"
  }
]
```

`external_id` et `tags` restent acceptés (voir `DatasetCase`) mais ne sont pas
requis. Pas de CSV. Un dataset créé manuellement (`origin: "manual"`) suit la
même forme `DatasetCase`, saisie ligne par ligne côté UI.

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
