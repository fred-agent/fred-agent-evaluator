# Deployment Guide — fred-agent-evaluator

## Images Docker

Deux images, construites depuis la racine du repo :

| Image | Dockerfile | Rôle |
|---|---|---|
| `fred-evaluation-api` | `apps/fred-evaluation-backend/dockerfiles/Dockerfile-api` | API REST :8336 (`/evaluation/v1`), porte aussi `alembic` |
| `fred-evaluation-worker` | `apps/fred-evaluation-backend/dockerfiles/Dockerfile-worker` | Worker Temporal (exécution + scoring) |

```bash
make docker-build

# Ou individuellement
make -C apps/fred-evaluation-backend docker-build-api
make -C apps/fred-evaluation-backend docker-build-worker
```

Les images prennent `fred-core`, `fred-sdk`, `fred-runtime` et `fred-pod` sur PyPI
(`UV_NO_SOURCES_PACKAGE`), bornées par les planchers de `pyproject.toml` : elles se
construisent depuis un clone seul, sans le checkout voisin `~/Fred/fred` utilisé en
développement. `fred-deepeval-cli` vient du repo.

La CI (`Build-and-push-docker.yml`) publie `swift-dev` sur chaque push de `swift`, et
`v<version>` sur un tag `code/v<version>`.

## Kubernetes (Helm)

Le chart `deploy/charts/fred-evaluator` vise une installation neuve :

| Ressource | Rôle |
|---|---|
| `Deployment <release>-api` | API ; un `initContainer` lance `alembic upgrade head` avant de démarrer |
| `Deployment <release>-worker` | Worker Temporal, sans Service |
| `Service <release>-api` | ClusterIP :8336, interne (pas d'Ingress) |
| `ConfigMap <release>-config` | `configuration.yaml` rendu depuis `values.configuration` |
| `Secret <release>-secret` | seulement avec `secret.create: true` |

La configuration complète vit dans `values.configuration` et est rendue telle quelle :
on surcharge ce qui diffère de l'installation Fred par défaut (hôtes PostgreSQL,
Keycloak, Temporal, Control Plane, runtime).

Les secrets arrivent en variables d'environnement (`envFrom`) depuis un Secret :

| Clé | Lue par |
|---|---|
| `FRED_POSTGRES_PASSWORD` | `storage.postgres` |
| `KEYCLOAK_EVAL_WORKER_CLIENT_SECRET` | `security.m2m` (worker) |
| `MISTRAL_API_KEY` | profils juge et analyse |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | seulement avec `tracer: langfuse` |

```bash
kubectl create secret generic fred-evaluator-secrets \
  --from-literal=FRED_POSTGRES_PASSWORD=... \
  --from-literal=KEYCLOAK_EVAL_WORKER_CLIENT_SECRET=... \
  --from-literal=MISTRAL_API_KEY=...

helm install fred-evaluator deploy/charts/fred-evaluator \
  --set secret.existingSecret=fred-evaluator-secrets \
  -f my-values.yaml
```

Les tags d'image suivent l'`appVersion` du chart (`v<appVersion>`) ; `api.image.tag` et
`worker.image.tag` les surchargent.

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `CONFIG_FILE` | chemin du `configuration.yaml` |
| `ENV_FILE` | chemin d'un `.env` optionnel ; les secrets peuvent aussi venir directement de l'environnement |

## Docker Compose (local)

`deploy/docker-compose/docker-compose.yml` lance les deux images contre
l'infrastructure de `fred-deployment-factory` (PostgreSQL et sa base `evaluation`,
Keycloak, Temporal) et un Control Plane démarré sur l'hôte. Les conteneurs partagent
le réseau de l'hôte et lisent `apps/fred-evaluation-backend/config/configuration_prod.yaml`
et `config/.env` : c'est `make run-prod` + `make run-worker-prod`, depuis les images.
Linux uniquement.

```bash
docker compose -f deploy/docker-compose/docker-compose.yml up --build
```

Un service `schema` applique `alembic upgrade head` avant que l'API et le worker ne
démarrent.
