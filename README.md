# fred-agent-evaluator

Evaluate Fred agents against datasets and inspect their answers and scores.
The evaluator is a separate application: a hosted UI, an API and a scoring worker.

On Weaver, deploy a dedicated evaluator for each organization, with its own
workload credentials and business database. The organization Owner (Responsable)
registers and authorizes it in **Administration > Features > Apps**. This connects
an already deployed service; it neither installs containers nor restarts Fred.
Start with the [deployment guide](docs/DEPLOYMENT_GUIDE.md) for the model, boundaries
and installation procedure. Swift keeps its separate Helm registration workflow.

## Structure

```
apps/
  fred-evaluation-backend/   # Evaluation API (FastAPI :8336) + Worker
  fred-evaluation-frontend/  # Hosted application UI
libs/
  fred-deepeval-cli/         # Scoring library (PyPI: fred-deepeval-cli)
deploy/
  charts/fred-evaluator/     # Helm chart — ui + api + worker; its README is the install doc
  k3d/build                  # Images from this checkout for a local k3d instance
  docker-compose/            # API + worker images against fred-deployment-factory
scripts/
  makefiles/                 # Shared Makefile includes
docs/
  ARCHITECTURE.md
  DEPLOYMENT_GUIDE.md
```

## Docker images

| Image | Role | Port |
|---|---|---|
| `fred-evaluation-api` | API REST + SSE | 8336 |
| `fred-evaluation-worker` | Worker Temporal (scoring) | — |
| `fred-evaluation-ui` | Hosted UI | 8080 |

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

Both resolve from PyPI through the committed `uv.lock`. To work on unreleased fred,
`make dev-local` with `FRED_REPO` set to your fred checkout (no default) overlays it, and
`FRED_LIBS=local` does the same for the images (fred-deployment-factory's docs/LOCAL-DEVELOPMENT.md, "Work on unreleased fred").
- `fred-deepeval-cli` — local editable (`libs/fred-deepeval-cli`)

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT_GUIDE.md)
- [Developer contract](docs/DEVELOPER_CONTRACT.md)
