# CLAUDE.md — fred-agent-evaluator

Operational instructions for AI assistants (Claude Code) working in this repository.

---

## Repository structure

```
apps/fred-evaluation-backend/   # FastAPI API + Temporal worker
apps/fred-evaluation-frontend/  # The evaluator's UI, a Fred application (iframe, @fred-oss/*)
libs/fred-deepeval-cli/         # Scoring library (published to PyPI)
deploy/
  charts/fred-evaluator/        # Helm chart (2 deployments: api + worker)
  docker-compose/               # API + worker images against fred-deployment-factory
docs/
  ARCHITECTURE.md               # Component diagram + end-to-end flow
  DEVELOPER_CONTRACT.md         # API contract + key rules
  DEPLOYMENT_GUIDE.md           # Docker + Helm + prod config
```

---

## Key rules

1. **`fred-*` libraries (`fred-core`, `fred-sdk`, `fred-runtime`) are published on PyPI** — `pyproject.toml`
   holds the version floors. In development, `[tool.uv.sources]` resolves them from the sibling
   `~/Fred/fred` checkout; the Docker images ignore those entries (`UV_NO_SOURCES_PACKAGE`) and take
   PyPI. Never make an image or CI depend on the sibling checkout.
2. **`fred-deepeval-cli` is the only local dependency** — editable install from `libs/`.
3. **Never add DeepEval/LiteLLM to API image deps** — scoring deps belong in `[scoring]` optional group only.
4. **Never expose worker via HTTP** — worker accesses DB directly.
5. **API never runs scoring** — `fred-deepeval-cli` is called exclusively by the worker.

---

## Development workflow

```bash
# Code quality (all submodules)
make code-quality
make code-quality-fix

# Tests
make test

# Run API locally
cd apps/fred-evaluation-backend
uv sync
make run          # :8336 (SQLite, no auth — see config/.env.template)

# Run worker locally
make run-worker
```

For a real observability session (security on, against the shared `fred-deployment-factory`
infra) rather than the quick no-auth start above, use the
`.claude/skills/live-observability-session` skill in this repo — it covers the
`configuration.yaml` vs `configuration_prod.yaml` split and the exact ports/preconditions.

---

## Commit conventions

- Format: `feat(EVAL-NN): description`
- One commit per logical change
- Never skip hooks (`--no-verify`)

---

## Before any change

1. Read `docs/DEVELOPER_CONTRACT.md` for API contract and invariants.
2. Read `docs/ARCHITECTURE.md` to understand component boundaries.
3. Check that the change does not blur the API/worker boundary.
