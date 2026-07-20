# Architecture — fred-agent-evaluator

## Vue d'ensemble

```
Frontend (fred)
     │
     │ REST / SSE
     ▼
fred-evaluation-backend (API)     ←── DB (SQLite dev / PostgreSQL prod)
     │                                        ▲
     │ DB directe                             │
     ▼                                        │
fred-evaluation-backend (Worker) ────────────┘
     │
     │ POST /agents/evaluate
     ▼
fred-runtime (fred repo)
     │
     │ EvalTrace
     ▼
fred-deepeval-cli (libs/)
     │
     │ LiteLLM
     ▼
LLM juge (Mistral / GPT-4 / etc.)
```

## Composants

### `apps/fred-evaluation-backend`

Deux processus distincts dans le même package Python :

**API** (`main.py`) — FastAPI sur le port 8333
- Reçoit les requêtes du frontend
- Valide et persiste les evaluations et leurs runs
- Expose les résultats via REST et SSE
- Ne connaît pas DeepEval

**Worker** (`main_worker.py`) — boucle autonome
- Poll la DB toutes les 5s
- Appelle fred-runtime `/agents/evaluate`
- Score via `fred-deepeval-cli`
- Persiste les résultats

### `libs/fred-deepeval-cli`

Librairie Python publiée sur PyPI.
- `resolve_profile()` — détecte auto RAG vs non-RAG
- Métriques RAG : Faithfulness, ContextualRelevancy, ContextualPrecision, ContextualRecall
- Métriques non-RAG : AnswerRelevancy
- LiteLLM comme routeur LLM universel

## Dépendances externes

| Package | Source | Rôle |
|---|---|---|
| `fred-core` | PyPI | Config, DB, Keycloak |
| `fred-sdk` | PyPI | EvalTrace, ExecutionGrant |
| `fred-deepeval-cli` | Local editable | Scoring |
| `deepeval` | PyPI (transitif) | Métriques |
| `litellm` | PyPI (transitif) | Routeur LLM |
| `temporalio` | PyPI | Orchestration worker |

## Flux bout en bout

0. Frontend `POST /evaluation/v1/evaluations` (une fois, réutilisable) → API persiste une
   `Evaluation` immuable et versionnée (nom + cas), retourne 201 + `evaluation_id`
1. Frontend `POST /evaluation/v1/evaluations/{id}/runs` `{team_id, target}` → API charge
   les cas de l'evaluation, les copie dans `EvaluationCaseRow`, persiste le run
   (`created_by` + `team_id`) avec son `RunSnapshot`, retourne 202
2. Worker détecte le run `pending` (poll mémoire) ou reçoit le workflow Temporal
3. Worker appelle Control Plane → obtient `evaluate_url` (pas de `execution_grant` signé : RUNTIME-07 rev.2 — l'autorisation se fait au niveau du pod runtime via le JWT de l'appelant + OpenFGA)
4. Worker `POST /agents/evaluate` → fred-runtime exécute l'agent → retourne `EvalTrace`
5. Worker passe `EvalTrace` à `fred-deepeval-cli` → scores calculés
6. Worker persiste résultats en DB, émet events SSE
7. Frontend reçoit updates via `GET /runs/{run_id}/events`

### Découpage evaluation / run

Deux domaines, deux responsabilités :

- `evaluations/` — la **définition** immuable et versionnée : nom, origine
  (`upload | manual`), cas. Créée directement, sans passer par le pipeline
  capture → triage → `:promote` (`QuestionSet`), qui reste à construire.
- `runs/` — une **exécution** de cette définition : cible, `RunSnapshot`
  (profil, judge, concurrence figés au démarrage), cas exécutés, résultats,
  events SSE.

C'est ce découpage qui permet de ré-exécuter une même evaluation sans écraser
les résultats précédents : chaque exécution est un run distinct. Un run ne
reçoit jamais de cas en ligne — ils viennent toujours de l'evaluation référencée.

## Identité sortante — API vs worker (RFC `EVAL-AUTH`)

Chaque appel Control Plane porte une identité **explicite**, jamais un défaut
implicite (`execution/outbound_auth.py`) :

- **API** (étape 1) : agit **au nom de l'appelant** — propage son bearer token
  verbatim (`UserAuthentication`), ou `NoAuthentication` en dev local sans
  Keycloak. L'API ne construit **aucun** client M2M (`main.py`).
- **Worker** (étapes 2-4, Temporal ou boucle mémoire) : agit sous sa **propre
  identité de service** (`ServiceAuthentication`, client Keycloak
  `fred-evaluation-worker`, `main_worker.py`). Il n'impersonne jamais un
  utilisateur.

Le token utilisateur ne franchit **jamais** la frontière worker : le payload
Temporal (`RunInput`) ne porte que `run_id` ; la ligne de run
persiste `created_by` + `team_id` (ancrage de légitimité), pas de credential ;
l'autorisation d'exécution est ré-évaluée à l'instant T via l'identité propre
du worker (jamais un instantané figé de l'utilisateur créateur).
