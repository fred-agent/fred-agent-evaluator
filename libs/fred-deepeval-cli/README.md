# fred-deepeval-cli

External CLI for evaluating one Fred agent turn through `POST /agents/evaluate`.

## Purpose

This project provides a small external CLI that:
- calls a Fred pod `/agents/evaluate` endpoint
- receives an `EvalTrace`
- classifies the turn outcome
- resolves an evaluation preset from `agent_tags`
- computes structural checks
- scores the trace with DeepEval

## Commands

```bash
make dev
make eval-dev
make test
make code-quality
make cli
make score BASE_URL=http://127.0.0.1:8000/fred/agents/v2 AGENT_ID=fred.test.assistant INPUT="echo bonjour" SESSION_ID=eval-001 USER_ID=alice
make sql-scenarios BASE_URL=http://127.0.0.1:8000/fred/agents/v2

## Documentation

| Topic | File |
| --- | --- |
| Evaluate any Fred agent pod | `docs/evaluating-any-fred-agent.md` |
| RAG evaluation — approach and metrics | `docs/rag-evaluation-rfc.md` |
| RAG local setup guide | `docs/rag-local-setup.md` |
| SQL evaluation | `docs/sql-evaluation.md` |
| OTel export strategy | `fred/docs/swift/rfc/AGENT-EVALUATION-RFC.md §13` |

## Architecture — EVAL-01 Phase 1

This CLI is being restructured into a reusable library core so the Fred
Control Plane evaluation worker can call it directly without spawning a subprocess.

- `fred_deepeval_cli/core/` — callable library (models, evaluator, profiles, scorer, judge factory)
- `fred_deepeval_cli/cli/` — thin CLI adapter over the core
- `fred_deepeval_cli/worker_adapter.py` — public entrypoint for the Control Plane worker

The CLI interface and JSON output remain unchanged.
See EVAL-01 Phase 1 issue and `fred/docs/swift/rfc/AGENT-EVALUATION-RFC.md §7.3`.