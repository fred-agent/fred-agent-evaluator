# Evaluation — LLM Analysis of Campaign Results

**Status**: [ ] not started
**Priority**: medium
**Depends on**: EVAL-METRIC-AVERAGES-BACKLOG.md

## Goal

Allow sharing campaign metric averages and results to a Fred LLM agent to obtain
an automatic comment and analysis of the campaign performance.

---

## Backend — fred-evaluation-backend

- [ ] Add `POST /campaigns/{id}/analyze` endpoint
- [ ] Send campaign stats (metric averages, verdict breakdown, structural checks summary) to the Fred runtime
- [ ] Return the generated analysis as text
- [ ] Choose which agent profile to use for analysis

## Frontend — fred

- [ ] Add "Analyze" button in the campaign detail page
- [ ] Display the LLM-generated commentary
