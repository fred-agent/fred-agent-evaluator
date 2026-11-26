# Fred evaluation application — UI

The evaluator's own user interface, delivered as a **Fred application** (app id
`evaluation`). Fred shows it in an iframe at `/team/<team id>/apps/evaluation`,
serves it at the registration-specific `/apps/<registration UUID>/`, and relays its API calls to the evaluation
backend through `/app-services/evaluation/teams/<team id>/...`.

It is a standalone React app. It talks to Fred only through the published
`@fred-oss/iframe-sdk` and is built from `@fred-oss/ui` and
`@fred-oss/design-tokens`, pinned to exact versions from npmjs
(`scripts/check-boundary.mjs` refuses any local link).

## Screens

Routes are relative to `/team/<team id>/apps/evaluation/` and follow the host's
URL, so links and reloads land on the same screen.

| Route                       | Screen                                                                                  |
| --------------------------- | --------------------------------------------------------------------------------------- |
| (root)                      | evaluations with debounced search, sorting, server pagination and confirmed deletion    |
| `evaluations/new`           | JSON import or manual cases, with validation and creation feedback                      |
| `evaluations/<id>`          | evaluation KPIs, sorted/paginated runs, rerun, delete and case previews                 |
| `evaluations/<id>/runs/new` | agent, built-in and custom G-Eval metrics and recap                                     |
| `runs/<id>`                 | live progress, outcome cards, metric averages, analysis, metadata and actions           |
| `runs/<id>/cases/<case-id>` | full case drawer, metric explanations, errors, structural checks and JSON copy/download |

Weaver evaluates managed Python instances only. The agent's configured model is
used for new runs and reruns; per-run model choice and `runtime_agent` targets
remain deferred. Analysis waits up to 3 minutes, subject to the proxy timeout.

## How it talks to Fred and to the backend

- **Context**: the team, locale, theme and route come from the host
  (`fred:context`); `team.id` is the Weaver organization/team/project space UUID.
  The UI never reads it from its own URL. Personal spaces have no applications.
- **API**: `client.request("evaluations")` — a path relative to the team. The
  host adds `/app-services/evaluation/teams/<team id>/` and the user's token;
  this code never sees a token or an upstream address.
- **Backend surface**: the `/teams/{team_id}/...` routes of
  `fred-evaluation-backend` (`hosted/`), which check that the team is granted
  the application, holds `run_evaluations` (or `manage_evaluation_corpus` for
  corpus mutations), and that every run or evaluation belongs to it. See
  `docs/DEVELOPER_CONTRACT.md` § "Surface de l'application Fred".
- **Types**: `src/shared/api/openapi.d.ts` is generated from the backend's
  `openapi.json` (`make generate-api`); `make code-quality` fails when it lags.
- **No SSE**: the host's request bridge returns complete responses only, so
  progress is polled.
- **Tables**: shared `DataTable` and `TablePagination`; evaluation/run lists use server totals.
- **Metrics**: incomplete custom metric rows are explicitly omitted, as shown in the recap.

## Deploy on Kubernetes

The `fred-evaluator` chart deploys this UI with the API and the worker, and
the deployment guide describes registry registration: see
`docs/DEPLOYMENT_GUIDE.md` (deploy, register, enable — the same for every Fred
application). The image is `make docker-build`; its `config.json` is mounted
at run time.

## Run it inside Fred, locally

Prerequisites: the backend API (`make run-prod`, :8336), Fred's Control Plane
and Fred's frontend (:5173) — the VS Code task **All Services PROD** starts the
API, the worker and this UI.

```bash
make public/config.json build
npx --no-install vite preview --host 0.0.0.0 --port 5181 --strictPort
```

Use the built preview for Fred integration so assets and `config.json` resolve
relative to the registration directory. `make run` remains the standalone Vite
development server.

`public/config.json` holds `hostOrigin`: the exact Fred origin the browser
uses (`http://localhost:5173` locally). Messages from any other origin are
ignored.

As the organization Owner, register it in **Administration > Features > Apps**:

- Logical name `evaluation`, entry permission `run_evaluations`.
- UI base URL `http://127.0.0.1:5181/` and API base URL
  `http://127.0.0.1:8336/` for local development. Use addresses reachable from
  the Control Plane process; Kubernetes installation uses service DNS instead.
- Review the registration, then authorize it in the same panel. Local space
  policy can restrict this organization authorization further.

The host and proxy resolve the current registration dynamically; no
`FRONTEND_APPLICATIONS_JSON` or `platform.application_sources` registration
is needed. Analyst/Owner business rights remain required independently of the
application offer. The API checks the same scope using the caller token.

The [developer contract](../../docs/DEVELOPER_CONTRACT.md#surface-de-lapplication-fred-evaluation)
records local k3d browser/worker acceptance and its verification limits.

## Commands

| Command                 | Does                                                                         |
| ----------------------- | ---------------------------------------------------------------------------- |
| `make run`              | dev server on :5181                                                          |
| `make test`             | unit tests (Vitest, jsdom)                                                   |
| `make code-quality`     | toolchain, dependency boundary, API types freshness, `tsc`, Prettier, ESLint |
| `make code-quality-fix` | Prettier + ESLint fixes                                                      |
| `make generate-api`     | regenerate the API types from the backend's `openapi.json`                   |
| `make build`            | static bundle in `dist/`                                                     |

Node 24 (24.21 or later, below 25), aligned with Weaver. `.nvmrc` and the
Docker build pin 24.22.2; the CI image build uses that Dockerfile. With nvm:

```bash
nvm install
nvm use
npm ci --no-audit --no-fund
```

The lockfile is maintained with npm 11.

The committed UI libraries are published `0.1.0-alpha.4` packages; no local
link or tarball reference belongs in the manifest or lockfile.
