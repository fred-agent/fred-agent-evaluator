# Developer Contract — fred-agent-evaluator

## Règles fondamentales

1. **Le frontend ne soumet jamais d'URL** — seulement des identifiants (`agent_instance_id`). Les URLs sont résolues par le Control Plane.
2. **L'API ne score jamais** — elle utilise DeepEval/LiteLLM pour le modèle d'analyse des résultats. Le scoring des cas via `fred-deepeval-cli` reste réservé au worker (`[scoring]`).
3. **Le worker n'expose pas d'HTTP** — il accède directement à la DB.
4. **Chaque cas est persisté indépendamment** — un crash du worker ne doit pas effacer les résultats déjà calculés.
5. **`fred-deepeval-cli` est la seule dépendance locale au repo** — `fred-core`, `fred-sdk` et `fred-runtime` sont publiées sur PyPI (planchers dans `pyproject.toml`). Le `uv.lock` commité les résout sur PyPI ; pour travailler sur un fred non publié, `make dev-local` avec `FRED_REPO` (sans valeur par défaut) installe votre checkout par-dessus.
6. **L'API et le worker n'utilisent jamais la même identité sortante** (RFC `EVAL-AUTH`, issue #33) — voir §Identity below.

## Weaver scope

`team_id` in the API and database stores a Weaver **space UUID**. The name is
retained for this increment; no database migration or column rename is needed.
Only managed Python agent instances can be evaluated. The Control Plane owns
space permissions and runtime routing; the runtime admits each delegated turn.

## Identity: API-user vs worker-service (RFC `EVAL-AUTH`)

Every API call to the Control Plane passes an explicit `OutboundAuth`
(`execution/outbound_auth.py`) — there is no default, so no call site can
silently pick the wrong identity:

| Component | Identity used | `OutboundAuth` variant |
|---|---|---|
| API (`main.py`, interactive `POST /evaluations`, `POST /evaluations/{id}/runs`) | the caller's own bearer token, propagated verbatim | `UserAuthentication` (security enabled) / `NoAuthentication` (local dev, security disabled) |
| Worker (`main_worker.py`, Temporal activities and polling `RunRunner`) | the worker's M2M identity (`fred-evaluation-worker` Keycloak client), calling the runtime directly | `M2MBearerAuth` |

Rules this enforces:

- `main.py` never builds an M2M token provider — the API's `ControlPlaneClient` has none, so a call that (by mistake) requested `ServiceAuthentication` fails fast with `RuntimeError` instead of silently sending an unauthenticated or wrong-identity request.
- The user's bearer token is **request-scoped only**. It lives in the `UserAuthentication` value passed to a single call — never on `ControlPlaneClient` (which only holds connection config + the worker's M2M provider), never in Temporal (`RunInput` carries `run_id` and `max_concurrency`), never in the `evaluation_run` table (which stores `created_by` + `team_id`, not a credential).
- A missing/malformed `Authorization` header fails closed with 401. That check is fred-core's own `authenticate_request` dependency (resolved before any route body runs) — the evaluator normalizes its unstructured error into its own envelope (see below). With security disabled (local dev), the API explicitly uses `NoAuthentication` rather than falling back to the worker's M2M identity.

## Stable error codes and the one public envelope

`execution/evaluator_errors.py` is the evaluator API's one error contract. It:

1. classifies **known Control Plane boundary failures** (`httpx.HTTPStatusError`,
   timeout/transport errors, and the dedicated `ControlPlaneInvalidResponseError`
   for a malformed 2xx body — see `execution/control_plane_client.py`) instead of
   returning a blanket 422. A local/programming/configuration defect (e.g.
   `RuntimeError`) is *not* caught here and propagates as a real server error;
2. normalizes fred-core's own unstructured 401/403 `HTTPException`s (e.g. `{"detail":
   "No authentication token provided"}`) into the same envelope. fred-core's
   `authenticate_request` dependency runs before any route body, so the evaluator's
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

Codes describe boundary failures independently of the resource involved:

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
| Evaluation absent, or of another team | 404 | `evaluation_not_found` |
| Run absent, or of another team (application surface) | 404 | `run_not_found` |
| Team not granted the `evaluation` application (application surface) | 403 | `application_not_granted` |
| Analysis model could not be initialized (both analysis surfaces) | 503 | `analysis_unavailable` |

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
| POST | `/evaluations/{id}/runs` | 202 | Démarrer un run — `{team_id, target, metrics, custom_metrics, agent_model_override}` (`extra: forbid`). Cible **`managed_instance` uniquement** (`runtime_agent` supprimé du contrat). `metrics` (obligatoire, non vide) est la sélection manuelle des métriques DeepEval à calculer ; `custom_metrics` (optionnel) porte les critères GEval. `agent_model_override` est désactivé sur Weaver : toute valeur non nulle est refusée en 422 explicite avant préparation ou persistance. Judge et concurrence restent fixés côté serveur et figés dans un `RunSnapshot`. |
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

**Autorisation par espace.** Les identifiants de run et d'evaluation sont
globaux : toute route `/evaluation/v1` qui en nomme un charge d'abord la ressource,
puis demande au Control Plane `POST /authorize/space` avec
`{"space_id": team_id, "permission": "run_evaluations"}` et le jeton de l'appelant.
Le scope vient de la ressource, jamais d'une équipe arbitraire désignée par le
client. `allowed: false` donne 403 `target_forbidden`, sans modification.
Une réponse HTTP 404 du Control Plane donne 404 `target_not_found`.
Dans le checkout Weaver examiné, `api.rs::probe` convertit aussi `NotFound` et
`Forbidden` en `200 {"allowed": false}` ; l'évaluateur ne déduit pas l'existence
ou l'appartenance d'un espace à partir d'un refus.
`tests/test_run_access.py` parcourt automatiquement les routes concernées.
La création d'un run vérifie aussi `run_evaluations` : `prepare-execution`
vérifie `read`, ce qui ne suffit pas pour autoriser une évaluation.

Il n'existe pas de `GET /evaluations/{id}` ce cycle — la liste transporte déjà
tout ce dont l'écran de sélection a besoin, et le démarrage d'un run charge les
cas de l'evaluation côté serveur (pas via l'API publique).

Ce cycle **(EVAL-04, première version)** ne couvre que les runs sur agent managé
(`managed_instance`). Sont volontairement différés : cible `runtime_agent` (sans équivalent Weaver), sélection du profil judge, réglages de concurrence/timeout, CSV, et
un écran de gestion des evaluations indépendant du démarrage d'un run.

## Surface de l'application Fred (`evaluation`)

**Point ouvert Weaver :** `list_team_application_ids` et `hosted/entitlement.py`
conservent leur contrat `/teams/{team_id}/applications`. L'hébergement et les
droits applicatifs Weaver sont un autre chantier. Cette surface ne constitue
pas une intégration Weaver validée ; utiliser `/evaluation/v1` pour le test décrit
plus bas. Les routes `/teams` ci-dessous sont celles de l'évaluateur historique.

L'UI de l'evaluator est une application Fred : Fred l'affiche dans un iframe
(`/apps/evaluation/`) et relaie ses appels via sa gateway, qui retire le
préfixe `/app-services/evaluation` et transmet `Authorization` tel quel. L'API
reçoit donc `/teams/{team_id}/...` **sans** `/evaluation/v1` : ces routes
(`hosted/`) sont montées à côté du routeur existant, qui reste en place.

| Méthode | Route | Équivalent `/evaluation/v1` |
|---|---|---|
| GET, POST | `/teams/{team_id}/evaluations` | `/evaluations` (`team_id` en query / body) |
| GET | `/teams/{team_id}/evaluations/{id}` | — (détail avec les cas ; propre à la surface de l'application) |
| DELETE | `/teams/{team_id}/evaluations/{id}` | `/evaluations/{id}` |
| GET, POST | `/teams/{team_id}/evaluations/{id}/runs` | `/evaluations/{id}/runs` |
| GET | `/teams/{team_id}/evaluations/{id}/runs/summary` | idem |
| GET, DELETE | `/teams/{team_id}/runs/{run_id}` | `/runs/{run_id}` |
| GET | `/teams/{team_id}/runs/{run_id}/cases`, `…/cases/{case_id}`, `…/report` | idem |
| POST | `/teams/{team_id}/runs/{run_id}/cancel`, `…/analyze` | idem |
| GET | `/teams/{team_id}/agent-instances` | — (agents de l'équipe, lus au Control Plane avec le jeton de l'appelant) |
| GET | `/teams/{team_id}/model-profiles` | — (liste vide sur Weaver ; choix du modèle différé) |
| GET | `/teams/{team_id}/metrics` | — (métriques intégrées ; `requires_expected_output`) |

Règles :

- **L'équipe vient du chemin, jamais du body** : les bodies sont
  `EvaluationDocument` et `RunSpec` (`extra: forbid`), sans `team_id`.
- **Droit d'accès** (`hosted/entitlement.py`) : chaque route demande au
  Control Plane `GET /teams/{team_id}/applications`, avec le jeton de
  l'appelant, et n'admet la requête que si `evaluation` y figure. La gateway
  n'autorise rien elle-même. Tout le reste est un refus : non-membre
  (`target_forbidden`), app non accordée (`application_not_granted`), Control
  Plane injoignable (`control_plane_unavailable`) ou incohérent
  (`control_plane_invalid_response`).
- **Appartenance** : une evaluation ou un run d'une autre équipe répond 404,
  comme une ressource absente, et n'est jamais modifié.
- **Pas d'alias `personal`** : le Control Plane le résout en `personal-<uid>`,
  différent pour chaque appelant, alors que les lignes sont rangées sous la
  valeur du chemin ; il est refusé (`application_not_granted`) avant tout appel.
- Ces règles sont vérifiées structurellement par `tests/test_hosted_app.py` :
  toute route ajoutée sans le contrôle d'accès, ou qui atteindrait la
  ressource d'une autre équipe, fait échouer la suite.
- **Pas de SSE** : le pont de requêtes de l'hôte ne transmet que des réponses
  complètes ; l'UI interroge `GET /teams/{team_id}/runs/{run_id}`.

## Metric selection (manual — replaces automatic profile detection for metrics)

`StartRunRequest.metrics: list[str]` is the caller's explicit, non-empty
selection of built-in DeepEval metrics — no automatic detection. Allowed ids
live in `runs/metrics_catalog.py` (API layer, zero `deepeval` dependency):
`answer_relevancy`, `faithfulness`, `contextual_relevancy`,
`contextual_precision`, `contextual_recall`. `contextual_precision` /
`contextual_recall` selected on a case with no `expected_output` are reported
with verdict `"skipped"` rather than erroring.

## Execution preparation and worker delegation (Weaver)

The API calls `resolve_managed_instance` once in `start_run`, with the caller's
request-scoped token. It sends
`POST /spaces/{space_id}/agent-instances/{agent_instance_id}/prepare-execution`
without query parameters. Weaver accepts only `session_id`, the paired
`model_source_id` / `model_upstream_id`, and `reasoning`; none is needed here.
The route requires an admitted user and cannot be called with a worker identity.

The response uses `space_id`, `runtime_id` and `agent_instance_id`. An absent
`execute_url` (JSON null, e.g. the embedded Rust executor) is a clear 422
`target_invalid`: choose a Python instance with synchronous execution support.
The API replaces the final `/agents/execute` with `/agents/evaluate`, resolves
relative paths against `control_plane.runtime_base_url`, and freezes the absolute
`evaluate_url` in `RunSnapshot` / `snapshot_json`. Absolute URLs keep the authority
returned by the Control Plane. The frontend never chooses a destination.

Both workers read this snapshot and **never call prepare-execution**. They send:

```text
POST {evaluate_url}?person={created_by}&run={run_id}&agent={agent_instance_id}
Authorization: Bearer <worker M2M token>
```

The JSON body carries `agent_instance_id`, `input`, and
`runtime_context: {space_id: team_id, team_id: team_id, user_id: created_by}`.
The canonical `space_id` is mandatory on Weaver; the legacy `team_id` is also
sent as the same scope. Query `person` and `agent` must match the body's user
and instance. No `session_id` is sent: the pod creates its own evaluation
session; a supplied id would be checked as an existing conversation.

The worker service token needs `fred-delegation:delegation_caller` (and the
corresponding audience/scope mapping). This permits trusted identity assertion;
it does not grant the person access to content. The runtime performs fresh
admission through the Control Plane. User credentials never reach storage or
Temporal. There is no `Bearer dev` fallback: a fabricated token cannot establish
trusted delegation; absent M2M configuration fails before any runtime request.

Older managed-instance snapshots without `evaluate_url` remain readable as
reports, but cannot execute on Weaver. Workers record an explicit failure asking
for a new run, without attempting browser preparation. `runtime_agent` targets
and their preparation client have been removed; no historical-target execution
or snapshot backfill is provided.

## Agent model choice (open)

Weaver model offers come from preparation's `models` field. A future model
selection must use `runtime_context.model_choice: {source_id, upstream_model_id}`.
Legacy `agent_model_override` / `agent_profile_overrides` are not sent to Weaver.
For this increment every non-null override (including an empty string) is
rejected at run creation with 422 `target_invalid`, and `list_team_model_profiles`
returns `[]` without a Control Plane call. The database column is retained.
`actual_model_name` remains the runtime's observed model, not a requested value.

## Metric traceability

`StartRunRequest.custom_metrics: list[CustomMetricSpecInput]` carries
GEval-scored, user-authored criteria (`name`, `criteria`, `parameters`,
`threshold`). It only validates shape — not whether `parameters` names are
valid `LLMTestCaseParams` members. Scoring-specific validation remains
worker-side (`fred_deepeval_cli.core.models.CustomMetricSpec`),
so an unknown parameter name surfaces as a per-case scoring error, not a
run-creation error.

`metrics` and `custom_metrics` are persisted verbatim (`metrics_json`, `custom_metrics_json` on
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
make run          # API sur :8336
make run-worker   # Worker
```

## Test manuel contre la stack Docker Weaver

Procédure à exécuter par le développeur : elle n'est pas une preuve de validation
bout en bout. Elle suppose un pod Python et les services Docker déjà disponibles.
Le rapport lit le **nom courant** de l'espace dans `GET /me/spaces`, avec le jeton
du lecteur : cette liste contient chaque espace où il détient un rôle direct, ce
qui est le cas de quiconque peut évaluer. L'UUID reste la référence ; un espace
absent de la liste ou un échec de lecture laisse `team_name: null` sans faire
échouer le rapport.

1. Choisir un utilisateur admis (CGU acceptées), disposant de `run_evaluations`
   et de `read` sur l'espace, et une instance Python exécutable dans cet espace.
   `analyst` accorde ces deux permissions dans la matrice actuelle ; `owner`
   seul n'accorde pas `read`. L'instance doit avoir un modèle utilisable sans
   override, et le pod doit accepter la délégation du worker.
2. Vérifier la configuration Keycloak effectivement déployée :
   `fred-evaluation-worker` est un client confidentiel avec service account,
   rôle `fred-delegation:delegation_caller` et audience `fred-delegation` dans
   son jeton. Le commit de deployment-factory ne prouve pas à lui seul que la
   configuration a été appliquée au realm en cours.
3. Dans `apps/fred-evaluation-backend`, créer un fichier local de configuration
   à partir de `config/configuration.yaml`. Adapter ces sections, en conservant
   un profil judge valide et sa clé fournisseur :

```yaml
storage:
  postgres:
    sqlite_path: /tmp/fred-evaluator-weaver/evaluation.sqlite3
security:
  user:
    enabled: true
    realm_url: http://keycloak:8080/realms/app
    client_id: app
  m2m:
    enabled: true
    realm_url: http://keycloak:8080/realms/app
    client_id: fred-evaluation-worker
    secret_env_var: KEYCLOAK_EVAL_WORKER_CLIENT_SECRET
control_plane:
  base_url: http://localhost:8222/control-plane/v1
  runtime_base_url: http://localhost:8000
scheduler:
  backend: memory
observability:
  tracer: logging
```

L'issuer de l'exemple correspond au profil prod Weaver du Control Plane. Utiliser
le nom réellement accepté par la stack pour les deux blocs de sécurité et pour
obtenir les jetons ; `keycloak` / `app-keycloak` doivent résoudre depuis l'hôte
si ces noms sont employés. `runtime_base_url` doit être joignable **par le worker**
et compléter la route publique renvoyée par préparation : `:8000` pour
`/fred/agents/v2/...`, ou `:8010` pour un pod samples qui publie
`/samples/agents/v1/...`. Pour plusieurs pods à URL relative, utiliser leur
origine commune de gateway. Une URL absolue fournie par Weaver reste inchangée.

4. Charger les secrets dans chaque terminal, sans modifier les dépendances :

```bash
cd ~/Work/common/fred-agent-evaluator/apps/fred-evaluation-backend
export CONFIG_FILE="$PWD/config/configuration_weaver_local.yaml"
export ENV_FILE="$PWD/config/.env"
read -rsp 'Secret du client fred-evaluation-worker : ' KEYCLOAK_EVAL_WORKER_CLIENT_SECRET
printf '\n'
export KEYCLOAK_EVAL_WORKER_CLIENT_SECRET
# Charger aussi la clé du judge choisi (MISTRAL_API_KEY dans le profil fourni).
mkdir -p /tmp/fred-evaluator-weaver
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn fred_evaluation_backend.main:create_app --factory --host 127.0.0.1 --port 8336
```

Dans un second terminal, avec le même `CONFIG_FILE`, `ENV_FILE` et les mêmes
secrets :

```bash
.venv/bin/python -m fred_evaluation_backend.main_worker
```

Ces commandes utilisent le venv avec l'overlay Weaver installé. Elles n'exécutent
aucun `uv sync`. Pour Temporal, remplacer `scheduler` par `backend: temporal` et
`temporal: {host: localhost:7233, namespace: default, task_queue: evaluation}`
dans les deux processus ; la commande worker reste identique.

5. Obtenir un jeton de la personne. Le client public `app` du template Keycloak
   local autorise le password grant ; si le realm déployé le désactive ou exige
   MFA, utiliser la connexion navigateur habituelle et son jeton utilisateur.
   Ne pas utiliser un jeton de service pour créer le run.

```bash
export KC_REALM=http://keycloak:8080/realms/app
read -rp 'Utilisateur : ' EVAL_USERNAME
read -rsp 'Mot de passe : ' EVAL_PASSWORD
printf '\n'
TOKEN=$(printf '%s' "$EVAL_PASSWORD" | curl --fail-with-body -sS \
  "$KC_REALM/protocol/openid-connect/token" \
  --data-urlencode grant_type=password --data-urlencode client_id=app \
  --data-urlencode "username=$EVAL_USERNAME" --data-urlencode 'password@-' \
  | jq -er .access_token)
unset EVAL_PASSWORD
export CP=http://localhost:8222/control-plane/v1
export EVAL=http://localhost:8336/evaluation/v1
curl --fail-with-body -sS "$CP/me/spaces" -H "Authorization: Bearer $TOKEN" | jq .
export SPACE_ID='<UUID choisi>'
curl --fail-with-body -sS "$CP/spaces/$SPACE_ID/agent-instances" \
  -H "Authorization: Bearer $TOKEN" | jq .
# Si next_cursor est non nul, lire la suite avec --get --data-urlencode "after=$CURSOR".
export INSTANCE_ID='<agent_instance_id Python choisi>'
```

6. Créer l'évaluation puis lancer un run sans override :

```bash
EVALUATION_ID=$(jq -n --arg space "$SPACE_ID" \
  '{team_id:$space,name:"weaver-smoke",origin:"manual",cases:[{input:"Présente-toi en une phrase."}]}' \
  | curl --fail-with-body -sS "$EVAL/evaluations" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data-binary @- \
  | jq -er .evaluation_id)
RUN_ID=$(jq -n --arg space "$SPACE_ID" --arg instance "$INSTANCE_ID" \
  '{team_id:$space,target:{kind:"managed_instance",agent_instance_id:$instance},metrics:["answer_relevancy"]}' \
  | curl --fail-with-body -sS "$EVAL/evaluations/$EVALUATION_ID/runs" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data-binary @- \
  | jq -er .run_id)
curl --fail-with-body -sS "$EVAL/runs/$RUN_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '{operational_state,verdict,snapshot}'
```

Vérifier `snapshot.evaluate_url`, puis consulter le run jusqu'à son état terminal.
`completed` ne suffit pas : contrôler le verdict, les erreurs d'exécution et de
scoring ainsi que la présence des résultats de métriques. Une URL nulle de la
préparation doit refuser la création en 422, avant tout run en base.

7. Lire et archiver le rapport, avec un jeton utilisateur encore valide :

```bash
curl --fail-with-body -sS "$EVAL/runs/$RUN_ID/report" \
  -H "Authorization: Bearer $TOKEN" > /tmp/weaver-evaluation-report.json
jq . /tmp/weaver-evaluation-report.json
```

Pour diagnostiquer un 403 du pod, vérifier le rôle de délégation, l'audience,
la personne créatrice, l'instance et les droits actuels de cette personne.
Ne pas désactiver la sécurité pour faire réussir le test. La sélection de modèle
et la surface applicative hébergée restent les points ouverts décrits plus haut.
