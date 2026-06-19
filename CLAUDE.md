# CLAUDE.md — fred-agent-evaluator

Operational instructions for AI assistants (Claude Code) working in this repository.

---

## Repository structure

```
apps/fred-evaluation-backend/   # FastAPI API + Temporal worker
libs/fred-deepeval-cli/         # Scoring library (published to PyPI)
deploy/
  charts/fred-evaluator/        # Helm chart (2 deployments: api + worker)
  docker-compose/               # Local stack
docs/
  ARCHITECTURE.md               # Component diagram + end-to-end flow
  DEVELOPER_CONTRACT.md         # API contract + key rules
  DEPLOYMENT_GUIDE.md           # Docker + Helm + prod config
```

---

## Key rules

1. **`fred-core` and `fred-sdk` come from PyPI** — never add local path overrides for them.
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
make run          # :8333

# Run worker locally
make run-worker
```

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
