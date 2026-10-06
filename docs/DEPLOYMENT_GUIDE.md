# Deployment Guide — fred-agent-evaluator

fred-agent-evaluator est **l'application Fred `evaluation`**. Fred la connaît
exactement comme toute autre application (`information-systems` de fred-rags,
les applications de fred-samples) : rien dans le code ni les images de Fred ne
lui est propre. Trois étapes distinctes, toujours les mêmes :

1. **Déployer** les images de l'application dans un namespace Kubernetes
   quelconque (ce chart).
2. **Enregistrer** l'application dans la configuration de Fred : une entrée au
   catalogue du Control Plane et une entrée pour la gateway du frontend, toutes
   deux sous `app_id: evaluation`.
3. **Activer** : un admin plateforme accorde `app:evaluation` aux équipes dans
   Admin > Fonctionnalités.

La référence côté Fred est `docs/swift/platform/FORKING_GUIDE.md`, § « Your own
applications », dans le dépôt Fred.

## 1. Déployer

### Images

| Image | Construite depuis | Rôle |
|---|---|---|
| `fred-evaluation-ui` | `apps/fred-evaluation-frontend/Dockerfile` (contexte : ce dossier) | L'UI, servie par nginx sous `/apps/evaluation/`, port 8080 |
| `fred-evaluation-api` | `apps/fred-evaluation-backend/dockerfiles/Dockerfile-api` (contexte : racine) | API, port 8336 ; porte aussi `alembic` |
| `fred-evaluation-worker` | `apps/fred-evaluation-backend/dockerfiles/Dockerfile-worker` (contexte : racine) | Worker Temporal : exécute les agents et score |

```bash
make docker-build   # les trois
```

Les images API et worker prennent `fred-core`, `fred-sdk`, `fred-runtime` et
`fred-pod` sur PyPI (`UV_NO_SOURCES_PACKAGE`), bornés par les planchers de
`pyproject.toml` : elles se construisent depuis un clone seul. L'image UI
épingle Node 22.13.0 et les `@fred-oss/*` en versions publiées exactes.

La CI (`Build-and-push-docker.yml`) publie les trois en `swift-dev` à chaque
push sur `swift`, et en `v<version>` sur un tag `code/v<version>`. Le chart
prend par défaut le tag `v<appVersion>` : publier `code/vX` et `chart/vX`
ensemble.

### Chart

`deploy/charts/fred-evaluator` vise une installation neuve, dans n'importe quel
namespace :

| Ressource | Rôle |
|---|---|
| `Deployment` / `Service <release>-ui` | l'UI, ClusterIP :8080 |
| `ConfigMap <release>-ui-config` | le `config.json` de l'UI (`hostOrigin`) |
| `Deployment` / `Service <release>-api` | l'API, ClusterIP :8336 ; un `initContainer` lance d'abord `alembic upgrade head` |
| `Deployment <release>-worker` | le worker, sans Service |
| `ConfigMap <release>-config` | `configuration.yaml`, rendu tel quel depuis `values.configuration` |
| `Secret <release>-secret` | seulement avec `secret.create: true` |

Rien n'est exposé, pas d'Ingress : la gateway de Fred atteint l'UI et l'API
dans le cluster.

Valeurs requises :

- `ui.hostOrigin` — l'origine exacte à laquelle les utilisateurs ouvrent Fred
  (`https://fred.example.com` : schéma, hôte, port non standard, sans chemin).
  L'UI ignore les messages de toute autre origine ; le chart refuse ce qui
  n'est pas une origine nue.
- `secret.existingSecret` (ou `secret.create`) — un Secret dont les clés
  arrivent en variables d'environnement dans l'API et le worker :

  | Clé | Lue par |
  |---|---|
  | `FRED_POSTGRES_PASSWORD` | `storage.postgres` |
  | `KEYCLOAK_EVAL_WORKER_CLIENT_SECRET` | `security.m2m` (worker) |
  | `MISTRAL_API_KEY` | modèles juge et analyse |
  | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | seulement avec `tracer: langfuse` |

  Ou, à la place (ou en complément), `extraEnvVars` : chaque variable lue
  clé par clé dans un Secret que la plateforme possède déjà
  (`valueFrom.secretKeyRef`), sous un autre nom de clé. C'est ce que fait
  l'instance k3d de fred-deployment-factory (`deploy/k3d/values.yaml`, ici)
  avec son Secret `fred-secrets`.

- `values.configuration` — surcharger ce qui diffère d'une installation Fred
  par défaut : adresses PostgreSQL, realm Keycloak, Temporal, Control Plane et
  runtime.

```bash
kubectl -n fred-apps create secret generic fred-evaluator-secrets \
  --from-literal=FRED_POSTGRES_PASSWORD=... \
  --from-literal=KEYCLOAK_EVAL_WORKER_CLIENT_SECRET=... \
  --from-literal=MISTRAL_API_KEY=...

helm install evaluator deploy/charts/fred-evaluator -n fred-apps \
  --set ui.hostOrigin=https://fred.example.com \
  --set secret.existingSecret=fred-evaluator-secrets \
  -f my-values.yaml
```

## 2. Enregistrer dans Fred

**`helm install` affiche les deux blocs**, avec les noms DNS complets des
Services de cette release déjà renseignés : les copier depuis ses notes plutôt
que les écrire à la main. Ils vont dans les values du chart Fred :

- `applications.control-plane-backend.configuration.platform` —
  `frontend.feature_flags.enableApplications: true` et une entrée
  `application_sources` : `app_id: evaluation`, `ui_prefix: /apps/evaluation`,
  version, icône, noms et descriptions en/fr. C'est ce que voient le catalogue
  et l'admin ; aucun tuple d'autorisation n'est écrit.
- `applications.frontend.env` — `FRONTEND_APPLICATIONS_JSON`, une entrée
  `{"app_id": "evaluation", "ui_upstream": "http://<release>-ui.<ns>.svc.cluster.local:8080", "service_upstream": "http://<release>-api.<ns>.svc.cluster.local:8336", "service_required": true}`
  ajoutée à la liste. Ce sont des adresses côté serveur ; le navigateur ne les
  voit jamais.

Les deux blocs ont été vérifiés avec les validateurs de Fred eux-mêmes (le
`scripts/application-proxy.mjs` de la gateway et l'`ApplicationSourceConfig`
du Control Plane). Rien ne recoupe les deux `app_id` : ils doivent valoir
`evaluation` tous les deux, ce que l'UI annonce aussi et ce que l'API vérifie.

L'Ingress de Fred ne change pas : sa règle `/` porte déjà `/apps/` et
`/app-services/` vers la gateway du frontend. Redémarrer le frontend et le
Control Plane de Fred pour charger l'enregistrement.

## 3. Activer

Un admin plateforme (ou feature manager) ouvre **Admin > Fonctionnalités**,
filtre **app**, et active `evaluation` pour chaque équipe collaborative
concernée, ou l'active par défaut pour toutes ; un refus explicite pour une
équipe l'emporte toujours. Cela écrit le grant ReBAC `app:evaluation`, avec la
même forme d'activation que les capabilities et les définitions de bases de
connaissance. Tant que ce n'est pas fait, aucune équipe ne voit l'application.
Les espaces personnels n'ont jamais d'application.

À l'exécution, l'API vérifie chaque requête `/teams/{team_id}/...` avec le
jeton de l'appelant auprès de `GET /control-plane/v1/teams/{team_id}/applications`
et refuse par défaut (`hosted/entitlement.py`).

### Vérifier avec un utilisateur extérieur à l'équipe

Exigé par le contrat d'application de Fred : avec un utilisateur qui n'est
**pas** membre d'une équipe activée, appeler via Fred
`GET /app-services/evaluation/teams/<id de l'équipe activée>/evaluations`.
Attendu : 403. Un 200 signifie que les données sont lisibles par tout le realm.

## Hors du contrat d'application

Ces éléments précèdent le modèle d'application et n'existent que pour l'UI
d'évaluation encore intégrée au frontend Fred (`TeamSettingsEvaluations`). Ne
rien y ajouter ; ils disparaissent avec cette UI :

- la location `/evaluation/` de la gateway du frontend Fred et sa variable
  `FRONTEND_EVALUATION_UPSTREAM` ;
- la surface `/evaluation/v1` de l'API.

## Docker Compose (local)

`deploy/docker-compose/docker-compose.yml` lance les trois images contre
l'infrastructure de `fred-deployment-factory` et un Control Plane démarré sur
l'hôte. L'API et le worker partagent le réseau de l'hôte et lisent
`apps/fred-evaluation-backend/config/configuration_prod.yaml` et `config/.env`
(Linux uniquement) ; un service `schema` applique d'abord les migrations. L'UI
écoute sur `127.0.0.1:5181` : l'enregistrer dans le frontend Fred local avec
`ui_upstream` `http://127.0.0.1:5181` et `service_upstream`
`http://127.0.0.1:8336` (voir le README de l'UI).

```bash
docker compose -f deploy/docker-compose/docker-compose.yml up --build
```
