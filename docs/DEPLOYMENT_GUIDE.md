# Deployment Guide — fred-agent-evaluator

## Images Docker

Deux images à builder et déployer :

| Image | Dockerfile | Rôle |
|---|---|---|
| `fred-evaluation-api` | `apps/fred-evaluation-backend/dockerfiles/Dockerfile-api` | API REST :8333 |
| `fred-evaluation-worker` | `apps/fred-evaluation-backend/dockerfiles/Dockerfile-worker` | Worker scoring |

```bash
# Build
make docker-build

# Ou individuellement
make -C apps/fred-evaluation-backend docker-build-api
make -C apps/fred-evaluation-backend docker-build-worker
```

## Kubernetes (Helm)

Le chart `deploy/charts/fred-evaluator` déploie **2 Deployments** :

```
fred-evaluator/
├── templates/
│   ├── deployment-api.yaml
│   ├── deployment-worker.yaml
│   ├── service-api.yaml
│   ├── configmap.yaml
│   └── secret.yaml
└── values.yaml
```

```bash
helm install fred-evaluator deploy/charts/fred-evaluator \
  --set api.image.tag=latest \
  --set worker.image.tag=latest \
  --set db.host=postgres.svc \
  --set keycloak.url=https://keycloak.example.com
```

## Variables de configuration

| Variable | Rôle | Exemple |
|---|---|---|
| `CONFIG_FILE` | Chemin vers configuration.yaml | `/config/configuration.yaml` |
| `ENV_FILE` | Chemin vers .env (secrets) | `/config/.env` |

## Configuration prod (`configuration_prod.yaml`)

```yaml
database:
  host: postgres.svc
  port: 5432
  name: evaluation
  schema: evaluation

security:
  user:
    enabled: true
    realm_url: https://keycloak.example.com/realms/app
    client_id: app

control_plane:
  base_url: https://fred.example.com/control-plane/v1
  runtime_base_url: https://fred-runtime.example.com
  service_token_env: CONTROL_PLANE_SERVICE_TOKEN

worker:
  max_concurrent_cases: 4
  poll_interval_seconds: 5
  judge_profiles:
    mistral-small:
      provider: litellm
      model: mistral/mistral-small-latest
      settings:
        api_key_env: MISTRAL_API_KEY
```

## Docker Compose (local)

```bash
cd deploy/docker-compose
docker compose up
```
