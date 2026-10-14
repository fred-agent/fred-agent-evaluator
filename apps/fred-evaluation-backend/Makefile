include ../../scripts/makefiles/config/INFO-fred-evaluation.mk

# === Python Utility ===
include ../../scripts/makefiles/python-vars.mk
include ../../scripts/makefiles/python-deps.mk
include ../../scripts/makefiles/python-run.mk
include ../../scripts/makefiles/python-code-quality.mk
include ../../scripts/makefiles/python-security.mk
include ../../scripts/makefiles/python-test.mk
include ../../scripts/makefiles/python-clean.mk
include ../../scripts/makefiles/python-openapi.mk
include ../../scripts/makefiles/alembic.mk
include ../../scripts/makefiles/help.mk

FRED_LOCAL_BASE := dev-scoring
FRED_LOCAL_PACKAGES := fred-core fred-pod fred-sdk fred-runtime
include ../../scripts/makefiles/python-fred-libs.mk

ENV_FILE := $(ROOT_DIR)/config/.env
export ENV_FILE

##@ Run


# Synced once per change of the manifest or the lock, like `dev`: a re-sync on
# every `make test` would drop a `make dev-local` overlay.
$(TARGET)/.full-env: pyproject.toml uv.lock $(TARGET)/.uv-installed
	flock $(TARGET)/.compiled.lock sh -c '$(UV) sync --extra dev --extra scoring --extra worker --extra otel --refresh-package fred-deepeval-cli && touch $(TARGET)/.compiled $@'

.PHONY: dev-scoring
dev-scoring: $(TARGET)/.full-env ## Install scoring+worker+otel extras required by the worker
	@echo "✅ Scoring dependencies installed."

# tests/ and fred_evaluation_backend/workers/ import fred_deepeval_cli (worker
# scoring code path). The shared `test` and `type-check` targets only pull in
# `--extra dev`, so require dev-scoring here too — running `make test` or
# `make type-check` on a fresh checkout must not assume `dev-scoring` or
# `run-worker` ran first.
.PHONY: test
test: dev-scoring

.PHONY: type-check
type-check: dev-scoring

# Same prerequisite as `type-check` above: a baseline must be recorded against the same
# resolved imports it will later be checked against, or the two disagree on a fresh
# checkout where the scoring extras are not installed yet.
.PHONY: baseline-type-check
baseline-type-check: dev-scoring

.PHONY: run-worker
run-worker: dev-scoring ## Run the evaluation worker (installs scoring deps automatically)
	ENV_FILE=$(ROOT_DIR)/config/.env $(UV) run python -m fred_evaluation_backend.main_worker

.PHONY: run-worker-prod
run-worker-prod: export CONFIG_FILE = ./config/configuration_prod.yaml
run-worker-prod: run-worker ## Run the evaluation worker with prod-like configuration (M2M enabled)

##@ Docker

.PHONY: docker-build-api
docker-build-api: fred-docker-check ## Build the API Docker image (FRED_LIBS=local: fred from FRED_REPO)
	docker build \
		--network=$(API_DOCKER_NETWORK) \
		$(FRED_DOCKER_ARGS) \
		-f dockerfiles/Dockerfile-api \
		-t $(IMAGE_FULL) \
		$(DOCKER_CONTEXT)

.PHONY: docker-build-worker
docker-build-worker: fred-docker-check ## Build the worker Docker image (FRED_LIBS=local: fred from FRED_REPO)
	docker build \
		--network=$(API_DOCKER_NETWORK) \
		$(FRED_DOCKER_ARGS) \
		-f dockerfiles/Dockerfile-worker \
		-t $(IMAGE_FULL)-worker \
		$(DOCKER_CONTEXT)

API_DOCKER_NETWORK ?= host
API_CONTAINER_NAME ?= fred-evaluation-api
WORKER_CONTAINER_NAME ?= fred-evaluation-worker
WORKER_DOCKER_NETWORK ?= host
