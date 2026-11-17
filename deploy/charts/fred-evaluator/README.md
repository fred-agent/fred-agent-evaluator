# fred-evaluator

The `evaluation` application of [Fred](https://github.com/ThalesGroup/fred): evaluate
agents against versioned test sets. It runs next to an existing Fred platform, in any
namespace, and Weaver exposes it according to the SQL registration and organization policy.

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
  --set configuration.storage.postgres.schema=evaluation \
  --set secret.existingSecret=fred-evaluator-secrets
```

The install prints the upstreams to register through Weaver administration (see
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

Nothing is exposed and there is no Ingress: Fred's Control Plane reaches the UI and
the API inside the cluster through its fixed frontend gateway routes.

## Prerequisites

What the target Fred platform must provide; the chart's defaults name the services of a
default Fred install (`postgres`, `keycloak`, `temporal:7233`, `control-plane-backend:8222`,
`fred-agents`).

- **PostgreSQL**: a database `evaluation` owned by a user `evaluation`. The API creates
  and migrates the schema itself. On Weaver, set
  `configuration.storage.postgres.schema: evaluation`; initialization creates that
  owning schema in the migration transaction before the Alembic version table.
- **Keycloak**, realm `app`: users sign in through the platform's `app` client, and the
  worker needs its own confidential client `fred-evaluation-worker`, with a service
  account holding `app/service_agent`. Weaver additionally requires the existing
  `fred-delegation/delegation_caller` role (including its audience) and the
  `client_id: fred-evaluation-worker` claim on service tokens. This is trust to
  assert the run creator, never a business permission. Use `security.profile: c3`
  and `security.delegation.act_for_people: true` with current Fred libraries.
- **Temporal**: the worker polls `evaluation` in its release line namespace (`fred-weaver` for Weaver); set `configuration.scheduler.temporal.namespace`.
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
| `configuration.worker.judge_profiles.<id>.settings`, `configuration.analysis.settings` | `max_attempts: 2`, `request_timeout: 60`, `max_calls_per_minute: 60` | load limits of one model, per process (N worker replicas: N × the cap); retries only on 429, 5xx, timeouts and connection errors |
| `configuration.observability` | log tracer, log and Prometheus KPIs | `tracer: langfuse`, OpenSearch KPIs |
| `configuration.observability.kpi.prometheus` | `enabled: true`, `address: 0.0.0.0`, `port: 9000` | both pods serve `/metrics` on a container port named `metrics`; a loopback address fails the render |
| `metricsService.enabled`, `metricsService.serviceMonitor.enabled` | `true`, `false` | scraped like Fred's applications: a `<release>-api-metrics` and a `<release>-worker-metrics` Service, and `prometheus.io/*` pod annotations, or a ServiceMonitor instead (Prometheus Operator CRDs) |

## Register and enable in Fred

On Weaver, `helm install` (or `helm get notes <release>`) prints the full UI and API
upstreams. A platform administrator creates the `evaluation` registration disabled
in **Admin > Applications**, with `entry_permission: run_evaluations`, checks it,
then enables it. The UI upstream includes
`/apps/evaluation/`; the API upstream ends at `/`. Control Plane stores this in SQL;
no per-application Helm values or Fred restart is needed.

An organization Owner authorizes the application for their organization. Local
space policy can restrict this offer further. Personal spaces are excluded, and
application availability never substitutes for `run_evaluations` or
`manage_evaluation_corpus` permissions. Swift retains its existing Helm
registration and team-grant workflow.

## Upgrade and uninstall

`helm upgrade` migrates the database before the new API serves (the init container).
A judge or analysis profile with `provider: openai` no longer starts: declare it as
`provider: litellm` with `name: openai/<model>` (and `settings.base_url` for another
OpenAI-compatible endpoint).
`helm uninstall` removes the workloads; the `evaluation` database and its data stay.

## Local development

[fred-deployment-factory](https://github.com/fred-agent/fred-deployment-factory) installs
this chart on a local k3d instance: `make k3d-app FRED=weaver APP=fred-evaluator` the published release,
`DIR=../fred-agent-evaluator` added to build the images from a checkout (its
`deploy/k3d/build`). Its `k3d-apps/fred-evaluator/values-weaver.yaml` is an example of a real
instance's values.
