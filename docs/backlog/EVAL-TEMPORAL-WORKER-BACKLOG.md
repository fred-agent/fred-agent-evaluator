# Evaluation — Temporal Worker

**Status**: [ ] not started
**Priority**: low

## Goal

Replace the in-house async runner with Temporal for durable, observable, and
retriable evaluation workflow execution.

---

## Work items

- [ ] Define Temporal activities and workflows for campaign execution
- [ ] Migrate `runner.py` and `activities.py` to the Temporal Python SDK
- [ ] Deploy Temporal infrastructure
- [ ] Robustness tests (retry, timeout, crash recovery)
- [ ] Update Helm chart and docker-compose for Temporal worker deployment
