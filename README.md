# fred-agent-evaluator

Monorepo for the Fred agent evaluation platform.

## Structure

```
apps/
  fred-evaluation-backend/   # Evaluation API (FastAPI :8333) + Worker
libs/
  fred-deepeval-cli/         # Scoring library (PyPI: fred-deepeval-cli)
deploy/
  charts/fred-evaluator/     # Helm chart — 2 deployments: api + worker
  docker-compose/            # Local stack
scripts/
  makefiles/                 # Shared Makefile includes
docs/
  ARCHITECTURE.md
  DEPLOYMENT_GUIDE.md
```

## Images Docker

| Image | Rôle | Port |
|---|---|---|
| `fred-evaluation-api` | API REST + SSE | 8333 |
| `fred-evaluation-worker` | Worker Temporal (scoring) | — |

## Quick start (local)

```bash
# API
cd apps/fred-evaluation-backend
uv sync
CONFIG_FILE=./config/configuration.yaml uv run alembic upgrade head
make run

# Worker (terminal séparé)
make run-worker
```

## Dependencies

- `fred-core` — PyPI (config, storage, Keycloak helpers)
- `fred-sdk` — PyPI (EvalTrace, ExecutionGrant contracts)
- `fred-deepeval-cli` — local editable (`libs/fred-deepeval-cli`)

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT_GUIDE.md)
- [Developer contract](docs/DEVELOPER_CONTRACT.md)
