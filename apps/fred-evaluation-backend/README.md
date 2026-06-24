# fred-evaluation-backend

Evaluation platform for Fred agents: a FastAPI API and a worker that run test
campaigns against a target agent and report quality metrics.

- **API** (`fred_evaluation_backend.main:create_app`, port `8333`) — accepts
  evaluation campaigns and exposes results/SSE.
- **Worker** (`python -m fred_evaluation_backend.main_worker`) — polls pending
  campaigns, asks the Control Plane to prepare execution, calls the target
  agent's `/agents/evaluate`, and scores traces via `fred-deepeval-cli`.

Configuration follows the Fred convention: a YAML file (`CONFIG_FILE`) plus an
env file (`ENV_FILE`). See `config/configuration.yaml` (dev) and
`config/configuration_prod.yaml`. Sections: `app`, `storage.postgres`,
`security` (`SecurityConfiguration`), `observability` (`tracer`/`langfuse`/`kpi`),
`control_plane`, `worker`.

## Develop

```bash
uv sync
CONFIG_FILE=./config/configuration.yaml uv run alembic upgrade head
make run          # API on :8333
make run-worker   # evaluation worker
make code-quality
make test
```

## Docker

```bash
make docker-build-api      # API image
make docker-build-worker   # worker image (installs scoring/worker/otel extras)
```

`fred-core` / `fred-sdk` come from PyPI; `fred-deepeval-cli` is the only local
path dependency (worker-only, via the `scoring` extra).
