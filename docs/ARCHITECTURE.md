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
- Valide et persiste les campagnes
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

0. Frontend `POST /evaluation/v1/datasets` (une fois, réutilisable) → API persiste un
   `EvaluationDataset` immuable et versionné, retourne 201 + `dataset_id`
1. Frontend `POST /evaluation/v1/campaigns` `{team_id, target, dataset_id}` → API charge
   le dataset référencé, copie ses cas dans `EvaluationCaseRow`, persiste la campagne
   (`created_by` + `team_id`), retourne 202
2. Worker détecte campagne `pending` (poll mémoire) ou reçoit le workflow Temporal
3. Worker appelle Control Plane → obtient `evaluate_url` (pas de `execution_grant` signé : RUNTIME-07 rev.2 — l'autorisation se fait au niveau du pod runtime via le JWT de l'appelant + OpenFGA)
4. Worker `POST /agents/evaluate` → fred-runtime exécute l'agent → retourne `EvalTrace`
5. Worker passe `EvalTrace` à `fred-deepeval-cli` → scores calculés
6. Worker persiste résultats en DB, émet events SSE
7. Frontend reçoit updates via `GET /campaigns/{id}/events`

### Domaine dataset (EVAL-04, 2026-07-16)

`datasets/{schemas,models}.py` existait déjà (Phase 1 de `EVAL-DATASET-BACKLOG.md`,
modèles + table uniquement, pas d'API). `EVAL-04` ajoute la première surface API :
`datasets/{store,service,api}.py`, sur le même patron que `campaigns/`. Un dataset est
créé directement (`origin: upload | manual`), sans passer par le pipeline
capture → triage → `:promote` (`QuestionSet`), qui reste à construire. Une campagne
référence un dataset par `dataset_id` — c'est la seule voie de création de campagne
désormais ; l'ancien payload `dataset`/`cases` en ligne a été retiré, pas conservé en
parallèle.

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
Temporal (`CampaignInput`) ne porte que `campaign_id` ; la ligne de campagne
persiste `created_by` + `team_id` (ancrage de légitimité), pas de credential ;
l'autorisation d'exécution est ré-évaluée à l'instant T via l'identité propre
du worker (jamais un instantané figé de l'utilisateur créateur).
