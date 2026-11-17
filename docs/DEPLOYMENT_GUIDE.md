# Deployment guide

The evaluator is an independent Fred application: UI, API and worker images.
The [chart README](../deploy/charts/fred-evaluator/README.md) owns Kubernetes
installation, prerequisites and configuration. The API migrates its PostgreSQL
schema; only the worker runs agents and scoring. The worker exposes no business HTTP API.

## Build and deploy

`make docker-build` builds all three images. By default they resolve published Fred
Python libraries from the committed lockfile. For unreleased Weaver libraries use
`FRED_LIBS=local FRED_REPO=/path/to/fred`; no checkout is required by default.
The UI builds with its `/apps/evaluation/` base path.

For the local factory, after preparing infrastructure and model credentials:

```bash
make k3d-app FRED=weaver APP=fred-evaluator DIR=/path/to/fred-agent-evaluator \
  FRED_LIBS=local FRED_REPO=/path/to/fred
```

Run this in `fred-deployment-factory`. Its Weaver values select the `fred-weaver`
Temporal namespace, `http://weaver.localhost:8088` host origin and the
`MISTRAL_API_KEY` key in the operator's `fred-model-credentials` Secret. The shared
`fred-secrets` supplies PostgreSQL and worker credentials. Current Weaver runtime
requires the worker's `fred-delegation/delegation_caller` role and `client_id`
claim, provisioned through the existing Keycloak service-client configuration.

## Register and authorize in Weaver

`helm get notes fred-evaluator -n fred-weaver` prints the registration addresses:

- Logical name: `evaluation`.
- Entry permission (`entry_permission`): `run_evaluations`.
- UI upstream: `http://fred-evaluator-ui.fred-weaver.svc.cluster.local:8080/apps/evaluation/`.
- API upstream: `http://fred-evaluator-api.fred-weaver.svc.cluster.local:8336/`.

A platform administrator creates the disabled registration in **Admin > Applications**,
then enables it after checking the upstreams. An organization Owner authorizes it;
local collective-space policy may restrict it further. Personal spaces are excluded.
Control Plane owns this SQL registration and evaluates access. Do not set
`application_sources`, `FRONTEND_APPLICATIONS_JSON` or `enableApplications` in Helm.
The frontend gateway forwards `/apps/*` and `/app-services/*` unchanged to Control
Plane; changing a registration requires no frontend or Control Plane restart.

Verify with a user outside an authorized collective space: a request to
`GET /app-services/evaluation/teams/<space-uuid>/evaluations` must return 403.
An offered application also requires `run_evaluations` for reads/runs and
`manage_evaluation_corpus` for corpus creation/deletion.

Swift keeps its existing Helm registration and team authorization workflow. The
factory has separate line values; do not deploy both evaluator releases against
the shared `evaluation` database simultaneously.

## Docker Compose

`deploy/docker-compose/docker-compose.yml` starts the three images against factory
infrastructure and a host Control Plane (Linux). API and worker use the host network,
`configuration_prod.yaml` and `config/.env`; the schema service migrates first.

```bash
docker compose -f deploy/docker-compose/docker-compose.yml up --build
```

Register the local UI as `http://127.0.0.1:5181/apps/evaluation/` and the API as
`http://127.0.0.1:8336/` when Control Plane runs on the host. Set the UI host origin
to Fred's browser origin. The shared legacy `/evaluation/v1` API also enforces
current application entitlement and business permissions.
