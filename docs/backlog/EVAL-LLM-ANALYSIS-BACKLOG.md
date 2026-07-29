# Evaluation — LLM Analysis of Run Results

**Status**: [x] implemented (backend)
**Priority**: medium
**Depends on**: EVAL-METRIC-AVERAGES-BACKLOG.md

## Goal

Send a completed run's metric averages and per-case results to an LLM and get
back an automatic commentary (summary, strengths, weaknesses, recommendations,
risk level) on how the target performed.

> Refreshed for the two-noun model (EVAL-05): the analysis is attached to a
> **run**, not a "campaign". The endpoints, model config, and response shape
> below reflect what is actually implemented.

---

## Backend — fred-evaluation-backend

- [x] `POST /runs/{run_id}/analyze` — analyse one completed run
      (`runs/api.py::analyze_run`).
- [x] Assemble run stats (verdict, case counters, metric averages) plus every
      case (input, verdict, per-metric scores and judge explanations) and send
      them to the analysis model (`execution/analysis_client.py::AnalysisClient`).
- [x] Return the analysis as a typed `RunAnalysisResponse`
      (`{run_id, analysis, cached}`); `analysis` is a `RunAnalysisResult`
      (`summary`, `strengths`, `weaknesses`, `recommendations`, `risk_level`).
- [x] Profile-aware prompt: `rag` / `sql` / `workflow` / `default` each steer the
      model toward the metrics that matter for that profile (`_PROFILE_FOCUS`).
- [x] Result is cached on the run (`evaluation_run.analysis_json`, stored wrapped
      as `{"analysis": {...}}`). A second call returns `cached: true` without
      re-invoking the model; the cached analysis is also embedded in the run
      report (`build_run_report`).
- [x] Provider-agnostic model, configurable independently from the scoring judge
      (see below).

### Behaviour / status codes

- `404` — run not found.
- `409` — run is not `completed` yet (nothing to analyse).
- `503` — no analysis model configured (`app.state.analysis_client is None`).

## Configuration — `configuration.analysis`

The analysis model is its own top-level config block so it can differ from the
scoring judge, while sharing the judge's `provider` / `name` / `settings` schema
(`ModelConfiguration`) and the shared `build_judge_model` factory
(`config/models.py::_default_analysis`, wired in `main.py`).

```yaml
# Model used to write the run analysis (separate from the scoring judge).
# Available providers: litellm | openai | ollama
analysis:
  provider: litellm
  name: mistral/mistral-small-latest
  settings:
    api_key_env: MISTRAL_API_KEY   # env var holding the API key
  # OpenAI (requires an OPENAI_API_KEY):
  # provider: openai
  # name: gpt-4o-mini
  # settings:
  #   api_key_env: OPENAI_API_KEY
  #   base_url: https://...        # optional: OpenAI-compatible endpoint
  # Ollama (local model, requires Ollama running):
  # provider: ollama
  # name: llama3
  # settings:
  #   base_url: http://localhost:11434
```

| Field               | Meaning                                                        |
| ------------------- | ------------------------------------------------------------- |
| `provider`          | `litellm` \| `openai` \| `ollama`.                            |
| `name`              | Model name for the chosen provider.                           |
| `settings.api_key_env` | Name of the env var holding the API key (never the key itself). |
| `settings.base_url` | Optional — OpenAI-compatible endpoint or Ollama host.        |

Omitting the block falls back to the default above (`litellm` /
`mistral-small`, key from `MISTRAL_API_KEY`).

## Frontend — fred

- [ ] "Analyze" button on the run detail page.
- [ ] Display the generated commentary (summary + strengths / weaknesses /
      recommendations / risk level), reusing the cached result on revisit.
