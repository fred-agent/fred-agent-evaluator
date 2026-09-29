# Fred evaluation application — UI

The evaluator's own user interface, delivered as a **Fred application** (app id
`evaluation`). Fred shows it in an iframe at `/team/<team id>/apps/evaluation`,
serves it at `/apps/evaluation/`, and relays its API calls to the evaluation
backend through `/app-services/evaluation/teams/<team id>/...`.

It is a standalone React app. It talks to Fred only through the published
`@fred-oss/iframe-sdk` and is built from `@fred-oss/ui` and
`@fred-oss/design-tokens`, pinned to exact versions from npmjs
(`scripts/check-boundary.mjs` refuses any local link).

## Screens

Routes are relative to `/team/<team id>/apps/evaluation/` and follow the host's
URL, so links and reloads land on the same screen.

| Route                       | Screen                                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| (root)                      | the team's evaluations                                                                                             |
| `evaluations/new`           | create one: import a JSON document or type cases in                                                                |
| `evaluations/<id>`          | an evaluation: its cases, run KPIs and runs; delete it                                                             |
| `evaluations/<id>/runs/new` | start a run: agent, metrics, optional model                                                                        |
| `runs/<id>`                 | a run: live progress (polled every 3 s until it ends), cases and scores, cancel, LLM analysis, JSON report, delete |

Known limits: model profiles show their id, since their display name is an
i18n key of Fred's own frontend; the analysis waits up to 3 minutes, but a
shorter timeout on Fred's gateway would still cut it.

## How it talks to Fred and to the backend

- **Context**: the team, locale, theme and route come from the host
  (`fred:context`); the UI never reads them from its own URL.
- **API**: `client.request("evaluations")` — a path relative to the team. The
  host adds `/app-services/evaluation/teams/<team id>/` and the user's token;
  this code never sees a token or an upstream address.
- **Backend surface**: the `/teams/{team_id}/...` routes of
  `fred-evaluation-backend` (`hosted/`), which check that the team is granted
  the application and that every run or evaluation belongs to it. See
  `docs/DEVELOPER_CONTRACT.md` § "Surface de l'application Fred".
- **Types**: `src/shared/api/openapi.d.ts` is generated from the backend's
  `openapi.json` (`make generate-api`); `make code-quality` fails when it lags.
- **No SSE**: the host's request bridge returns complete responses only, so
  progress is polled.
- **Tables**: `@fred-oss/ui` has no table yet; the list uses a plain `<table>`
  styled with design tokens, pending a shared component.

## Deploy on Kubernetes

The `fred-evaluator` chart deploys this UI with the API and the worker, and
`helm install` prints the exact Fred registration: see
`docs/DEPLOYMENT_GUIDE.md` (deploy, register, enable — the same for every Fred
application). The image is `make docker-build`; its `config.json` is mounted
at run time.

## Run it inside Fred, locally

Prerequisites: the backend API (`make run-prod`, :8336), Fred's Control Plane
and Fred's frontend (:5173) — the VS Code task **All Services PROD** starts the
API, the worker and this UI.

```bash
make run   # :5181 — creates public/config.json from config.example.json once
```

`public/config.json` holds `hostOrigin`: the exact Fred origin the browser
uses (`http://localhost:5173` locally). Messages from any other origin are
ignored.

Register the application on the Fred side (configuration, no code):

1. Fred frontend gateway — `apps/frontend/.env` in the Fred checkout, one more
   entry in the list:

   ```dotenv
   FRONTEND_ENABLE_APPLICATIONS=true
   FRONTEND_APPLICATIONS_JSON='[..., {"app_id":"evaluation","ui_upstream":"http://127.0.0.1:5181","service_upstream":"http://127.0.0.1:8336","service_required":true}]'
   ```

2. Control Plane — `platform.application_sources` in its configuration
   (`frontend.feature_flags.enableApplications: true` must be set):

   ```yaml
   - app_id: evaluation
     ui_prefix: /apps/evaluation
     version: 0.1.0
     icon: fact_check
     display_name:
       en: "Evaluation"
       fr: "Évaluation"
     description:
       en: "Evaluate agents against versioned test sets."
       fr: "Évaluer les agents sur des jeux de tests versionnés."
     enabled: true
   ```

3. Enable it: Admin > Features, filter "app", enable `evaluation` for a
   collaborative team (this writes the `app:evaluation` grant). Personal
   spaces get no applications.

Restart the Fred frontend and the Control Plane to reload both halves. The
`app_id` must match exactly in both places; nothing cross-checks them.

## Commands

| Command                 | Does                                                                         |
| ----------------------- | ---------------------------------------------------------------------------- |
| `make run`              | dev server on :5181                                                          |
| `make test`             | unit tests (Vitest, jsdom)                                                   |
| `make code-quality`     | toolchain, dependency boundary, API types freshness, `tsc`, Prettier, ESLint |
| `make code-quality-fix` | Prettier + ESLint fixes                                                      |
| `make generate-api`     | regenerate the API types from the backend's `openapi.json`                   |
| `make build`            | static bundle in `dist/`                                                     |

Node 22 (22.13 or later). The lockfile was first resolved with npm 11, which
avoids an npm 10.9 resolver crash on this dependency set; `npm ci` with npm 10
installs from it normally.
