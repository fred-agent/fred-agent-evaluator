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
`fred-pod` sur PyPI, d'après le `uv.lock` commité : elles se construisent depuis un clone
seul. Avec `FRED_LIBS=local` et `FRED_REPO` (sans valeur par défaut), elles les prennent
dans votre checkout de fred (docs/LOCAL-DEVELOPMENT.md de fred-deployment-factory, « Work on unreleased fred »). L'image UI
épingle Node 22.13.0 et les `@fred-oss/*` en versions publiées exactes.

La CI (`Build-and-push-docker.yml`) publie les trois en `swift-dev` à chaque
push sur `swift`, et en `v<version>` sur un tag `code/v<version>`. Le chart
prend par défaut le tag `v<appVersion>` : publier `code/vX` et `chart/vX`
ensemble.

### Chart

Le chart `deploy/charts/fred-evaluator` est publié en
`oci://ghcr.io/fred-agent/fred-evaluator-helm/fred-evaluator` (tag `chart/v<version>`).
Sa documentation, [deploy/charts/fred-evaluator/README.md](../deploy/charts/fred-evaluator/README.md),
est la référence pour l'installer et le configurer : ressources créées,
prérequis côté Fred, valeurs requises, clés du Secret, adresses à surcharger.
`helm show readme` l'affiche depuis le chart publié.

### Certificats TLS sortants et rotation des secrets

Pour joindre Keycloak ou les endpoints de modèles avec une CA privée, créer un
Secret dans le namespace de l'evaluator contenant un bundle PEM, puis configurer :

```yaml
trustedCA:
  existingSecret: evaluator-trusted-ca
  key: ca.crt
```

Le chart monte ce bundle en lecture seule dans `/etc/fred/trusted-ca/ca.pem` et
définit `SSL_CERT_FILE` et `REQUESTS_CA_BUNDLE` pour l'API, son initContainer de
migration et le worker. Le montage reste séparé de la configuration et fonctionne
avec un filesystem racine en lecture seule. Sans `existingSecret`, le comportement
TLS par défaut est conservé. Le bundle remplace les autorités par défaut : inclure
les CA publiques et privées nécessaires à tous les endpoints utilisés.

Avec `secret.create: true`, une modification de `secret.data` change l'annotation
de checksum et déclenche le redémarrage des pods API et worker au prochain upgrade
Helm. Après rotation d'un Secret externe ou du bundle CA, redémarrer explicitement
ces Deployments ; leur contenu n'est pas inclus dans le checksum du chart.

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
