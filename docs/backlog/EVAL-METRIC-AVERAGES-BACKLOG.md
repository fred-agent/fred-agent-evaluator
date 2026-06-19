# Evaluation — Metric Averages per Campaign

**Status**: [ ] not started
**Priority**: high

## Goal

Replace the global success rate (not meaningful) with per-metric average scores
across all cases of a campaign.

---

## Backend — fred-evaluation-backend

- [ ] Add `metric_averages: dict[str, float]` JSON field to the campaign model
- [ ] Compute averages in `runner.py` when finalizing the campaign
- [ ] Add Alembic migration for the new column
- [ ] Expose `metric_averages` in the campaign API response (`schemas.py`, `service.py`)

## Frontend — fred

- [ ] Remove the "Taux de réussite global" KPI card
- [ ] Display per-metric averages in the campaign detail page
- [ ] Display per-metric averages in the campaign list
