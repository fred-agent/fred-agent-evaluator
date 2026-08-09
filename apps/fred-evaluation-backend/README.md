# fred-evaluation-backend

Evaluation platform for Fred agents: a FastAPI API and a worker that run test
campaigns against a target agent and report quality metrics.

- **API** (`fred_evaluation_backend.main:create_app`, port `8336`) — accepts
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
cp config/.env.template config/.env
# Edit config/.env: set MISTRAL_API_KEY and select CONFIG_FILE when needed.
make db-upgrade
make run          # API on :8336
make run-worker   # evaluation worker
make code-quality
make test
```

## Environment file — first-time setup

The evaluator follows the shared FRED configuration convention:

- `config/configuration.yaml` contains non-secret local settings: enabled model
  profiles, service URLs, scheduler, storage, and security switches.
- `config/.env` contains secrets. It is loaded by both the API and worker and is
  intentionally ignored by Git. It may also select the non-secret YAML path with
  `CONFIG_FILE`.
- `config/.env.template` documents every supported variable and is safe to commit
  because it contains no credential values.

Create the effective file once:

```bash
cp config/.env.template config/.env
```

The regular Make targets deliberately set only `ENV_FILE`. The shared FRED loader
loads that dotenv file first and then resolves `CONFIG_FILE` from it. Consequently,
the same selection applies to both processes:

```dotenv
# Development fallback when omitted: ./config/configuration.yaml
CONFIG_FILE="./config/configuration_prod.yaml"  # Docker Compose / production-like
```

This production-like profile assumes the evaluator processes run on the host and
use the ports exposed by `fred-deployment-factory`: PostgreSQL on
`localhost:5432`, Control Plane on `localhost:8222`, runtime ingress on
`localhost:8000`, and Temporal on `localhost:7233`. The factory maps
`app-keycloak` to the local Keycloak endpoint during Compose setup.

With that line present, use the ordinary commands:

```bash
make run
make run-worker
```

`make run-prod` and `make run-worker-prod` remain explicit command-line shortcuts;
they override dotenv selection for that invocation.

For the default local configuration, fill only:

```dotenv
MISTRAL_API_KEY="<API key issued by Mistral Studio>"
```

`MISTRAL_API_KEY` is a secret credential, not the `mistral-small` model name. If
another local FRED application stores a **Mistral-issued** key under
`OPENAI_API_KEY` because it uses an OpenAI-compatible client, the same secret may
also be assigned to `MISTRAL_API_KEY` here. An API key actually issued by OpenAI
cannot authenticate to Mistral.

LiteLLM is the evaluator's model-routing library. The default Mistral profile uses
LiteLLM but explicitly reads `MISTRAL_API_KEY`; it does **not** require
`LITELLM_API_KEY`. That variable is only for a deliberately configured LiteLLM
Proxy or custom profile.

Additional variables are conditional:

| Variable | When it is needed |
|---|---|
| `KEYCLOAK_EVAL_WORKER_CLIENT_SECRET` | `security.m2m.enabled: true`; must belong to the dedicated `fred-evaluation-worker` client |
| `FRED_POSTGRES_PASSWORD` | PostgreSQL configuration; not local SQLite |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Langfuse trace export and links |
| `OPENAI_API_KEY` | An explicitly configured OpenAI model profile |
| `LITELLM_API_KEY` | An explicitly configured authenticated LiteLLM Proxy/custom endpoint |
| `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION` | An explicitly configured Vertex AI profile |

Never copy another service's complete `.env`, reuse another service's Keycloak
client secret, or commit the effective `config/.env`.

## Docker

```bash
make docker-build-api      # API image
make docker-build-worker   # worker image (installs scoring/worker/otel extras)
```

`fred-core` / `fred-sdk` come from PyPI; `fred-deepeval-cli` is the only local
path dependency (worker-only, via the `scoring` extra).
