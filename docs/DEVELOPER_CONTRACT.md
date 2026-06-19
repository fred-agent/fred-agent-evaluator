# Developer Contract — fred-agent-evaluator

## Règles fondamentales

1. **Le frontend ne soumet jamais d'URL** — seulement des identifiants (`runtime_id`, `agent_instance_id`). Les URLs sont résolues par le Control Plane.
2. **L'API ne score jamais** — DeepEval est une dépendance du worker uniquement (`[scoring]`).
3. **Le worker n'expose pas d'HTTP** — il accède directement à la DB.
4. **Chaque cas est persisté indépendamment** — un crash du worker ne doit pas effacer les résultats déjà calculés.
5. **`fred-deepeval-cli` est la seule dépendance locale** — `fred-core` et `fred-sdk` viennent de PyPI.

## API contract

Base URL : `/evaluation/v1`

| Méthode | Route | Status | Description |
|---|---|---|---|
| POST | `/campaigns` | 202 | Créer une campagne |
| GET | `/campaigns` | 200 | Lister (param: `team_id`) |
| GET | `/campaigns/{id}` | 200 | Détail + agrégats |
| GET | `/campaigns/{id}/cases` | 200 | Cas paginés (max 200) |
| GET | `/campaigns/{id}/cases/{case_id}` | 200 | Détail d'un cas |
| GET | `/campaigns/{id}/events` | 200 | SSE temps réel |
| POST | `/campaigns/{id}/cancel` | 202 | Annuler |

## Scoring profiles

- `"auto"` — détection automatique RAG vs non-RAG via `resolve_profile()` dans fred-deepeval-cli
- RAG détecté si `retrieval_context` non vide dans l'EvalTrace
- `ContextualPrecision` et `ContextualRecall` nécessitent `expected_output` dans le cas

## Format dataset JSON

```json
[
  {
    "input": "Question posée à l'agent",
    "expected_output": "Réponse attendue (optionnel, requis pour ContextualPrecision/Recall)",
    "external_id": "mon-id-custom (optionnel)"
  }
]
```

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
