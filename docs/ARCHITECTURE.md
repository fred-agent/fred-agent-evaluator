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

1. Frontend `POST /evaluation/v1/campaigns` → API persiste, retourne 202
2. Worker détecte campagne `pending`
3. Worker appelle Control Plane → obtient execute_url + execution_grant
4. Worker `POST /agents/evaluate` → fred-runtime exécute l'agent → retourne `EvalTrace`
5. Worker passe `EvalTrace` à `fred-deepeval-cli` → scores calculés
6. Worker persiste résultats en DB, émet events SSE
7. Frontend reçoit updates via `GET /campaigns/{id}/events`
