# fred-evaluator

The `evaluation` application of [Fred](https://github.com/ThalesGroup/fred): evaluate
agents against versioned test sets. It runs next to an existing Fred platform, in any
namespace, and Fred shows it to the teams a platform admin enables it for.

## TL;DR

```bash
kubectl create namespace fred-apps
kubectl -n fred-apps create secret generic fred-evaluator-secrets \
  --from-literal=FRED_POSTGRES_PASSWORD=... \
  --from-literal=KEYCLOAK_EVAL_WORKER_CLIENT_SECRET=... \
  --from-literal=MISTRAL_API_KEY=...

helm install evaluator oci://ghcr.io/fred-agent/fred-evaluator-helm/fred-evaluator \
  --version <version> -n fred-apps \
  --set ui.hostOrigin=https://fred.example.com \
  --set secret.existingSecret=fred-evaluator-secrets
```

The install prints the two blocks to add to Fred's configuration (see
[Register and enable](#register-and-enable-in-fred)). Chart `X.Y.Z` runs images `vX.Y.Z`.

## What it deploys

| Resource | Role |
| --- | --- |
| `Deployment` / `Service <release>-ui` | the UI, a static bundle Fred shows in an iframe, ClusterIP `ui.port` |
| `Deployment` / `Service <release>-api` | the API, ClusterIP `api.port`; an init container runs `alembic upgrade head` first |
| `Deployment <release>-worker` | the Temporal worker that runs agents and scores cases; no Service |
| `ConfigMap <release>-config` | `configuration.yaml` for the API and the worker, rendered from `configuration` |
| `ConfigMap <release>-ui-config` | the UI's `config.json` (`ui.hostOrigin`) |
| `Secret <release>-secret` | only with `secret.create: true` |

Nothing is exposed and there is no Ingress: Fred's frontend gateway reaches the UI and
the API inside the cluster.

## Prerequisites

What the target Fred platform must provide; the chart's defaults name the services of a
default Fred install (`postgres`, `keycloak`, `temporal:7233`, `control-plane-backend:8222`,
`fred-agents`).

- **PostgreSQL**: a database `evaluation` owned by a user `evaluation`. The API creates
  and migrates the schema itself.
- **Keycloak**, realm `app`: users sign in through the platform's `app` client, and the
  worker needs its own confidential client `fred-evaluation-worker`, with a service
  account holding the client role `app/service_agent` and nothing else.
- **Temporal**: the worker polls the task queue `evaluation`.
- **A judge model**: the defaults use Mistral through LiteLLM (`MISTRAL_API_KEY`); any
  LiteLLM provider works, see `configuration.worker.judge_profiles` and
  `configuration.analysis`.

## Configure

### Required

| Value | Meaning |
| --- | --- |
| `ui.hostOrigin` | The exact origin users open Fred at: scheme, host, non-default port, no path (`https://fred.example.com`). The UI ignores messages from any other origin; the chart refuses anything that is not a bare origin. |
| Credentials | `secret.existingSecret`, `secret.create` or `extraEnvVars`, see below. The chart refuses to render without one. |

### Credentials

The API and the worker read these environment variables:

| Key | Read by |
| --- | --- |
| `FRED_POSTGRES_PASSWORD` | `configuration.storage.postgres` |
| `KEYCLOAK_EVAL_WORKER_CLIENT_SECRET` | `configuration.security.m2m`, the worker's identity |
| `MISTRAL_API_KEY` | the judge and analysis models (whatever `api_key_env` names) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | only with `configuration.observability.tracer: langfuse` |

Three ways to provide them, which can be combined:

- `secret.existingSecret`: a Secret you manage, with exactly these keys (recommended);
- `extraEnvVars`: each variable read from a Secret the platform already owns, under
  another key name (`valueFrom.secretKeyRef`);
- `secret.create: true` with `secret.data`: the chart renders the Secret. Convenient for a
  test, not for real credentials.

### Addresses

Override under `configuration` whatever differs from a default Fred install:

| Value | Default |
| --- | --- |
| `configuration.storage.postgres.host` / `port` / `database` / `username` | `postgres` / `5432` / `evaluation` / `evaluation` |
| `configuration.security.user.realm_url` and `configuration.security.m2m.realm_url` | `http://keycloak/realms/app` |
| `configuration.security.authorized_origins` | `[]`; the browser origins the API accepts (CORS), usually Fred's origin |
| `configuration.scheduler.temporal.host` / `task_queue` | `temporal:7233` / `evaluation` |
| `configuration.control_plane.base_url` | `http://control-plane-backend:8222/control-plane/v1` |
| `configuration.control_plane.runtime_base_url` | `http://fred-agents` |

`configuration` is rendered verbatim as the backend's `configuration.yaml`: the backend
validates it at startup, and a pod that fails to start says which key is wrong.

### Optional

| Value | Default | Meaning |
| --- | --- | --- |
| `api.image`, `ui.image`, `worker.image` | `ghcr.io/fred-agent/fred-evaluation-{api,ui,worker}`, tag `v<appVersion>` | another registry or tag |
| `imagePullSecrets` | `[]` | for a private registry |
| `api.replicas`, `ui.replicas`, `worker.replicas` | `1` | |
| `api.resources`, `ui.resources`, `worker.resources` | see `values.yaml` | |
| `configuration.worker.max_concurrent_cases` | `1` | cases one worker replica runs at once; each one is a live agent turn plus judge calls |
| `configuration.observability` | log tracer, log KPIs | `tracer: langfuse`, Prometheus or OpenSearch KPIs |

## Register and enable in Fred

Fred knows an application only through its own configuration. `helm install` prints both
blocks with this release's service names filled in (`helm get notes <release>` prints them
again):

1. in the Fred chart's values, an `application_sources` entry for the Control Plane and a
   `FRONTEND_APPLICATIONS_JSON` entry for the frontend gateway, both with
   `app_id: evaluation`; restart the Control Plane and the frontend;
2. a platform admin opens **Admin > Features**, filters **app**, and enables `evaluation`
   for the teams that should see it. Until then, no team does.

## Upgrade and uninstall

`helm upgrade` migrates the database before the new API serves (the init container).
`helm uninstall` removes the workloads; the `evaluation` database and its data stay.

## Local development

`deploy/k3d/` in the [source repository](https://github.com/fred-agent/fred-agent-evaluator)
installs this same chart on a local k3d instance with
[fred-deployment-factory](https://github.com/fred-agent/fred-deployment-factory)
(`make k3d-app DIR=../fred-agent-evaluator`): its `values.yaml` is an example of a real
instance's values. `RELEASE=<version>` deploys that published chart and its images
instead, without building, still with the checkout's k3d values.
