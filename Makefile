CODE_QUALITY_DIRS := libs/fred-deepeval-cli apps/fred-evaluation-backend
TEST_DIRS        := libs/fred-deepeval-cli apps/fred-evaluation-backend

.DEFAULT_GOAL := help

##@ Code quality

.PHONY: code-quality
code-quality: ## Run code quality checks in all submodules
	@set -e; \
	for dir in $(CODE_QUALITY_DIRS); do \
		echo "************ Running code-quality in $$dir ************"; \
		$(MAKE) -C $$dir code-quality; \
	done

.PHONY: code-quality-fix
code-quality-fix: ## Auto-fix formatting/imports/linting in all submodules
	@set -e; \
	for dir in $(CODE_QUALITY_DIRS); do \
		echo "************ Running code-quality fixes in $$dir ************"; \
		$(MAKE) -C $$dir code-quality-fix; \
	done

##@ Tests

.PHONY: test
test: ## Run tests in all submodules
	@set -e; \
	for dir in $(TEST_DIRS); do \
		echo "************ Running tests in $$dir ************"; \
		$(MAKE) -C $$dir test; \
	done

##@ Clean

.PHONY: clean
clean: ## Clean all submodules
	@set -e; \
	for dir in $(CODE_QUALITY_DIRS); do \
		echo "************ Cleaning $$dir ************"; \
		$(MAKE) -C $$dir clean; \
	done

##@ Docker

.PHONY: docker-build
docker-build: ## Build all Docker images (api + worker)
	$(MAKE) -C apps/fred-evaluation-backend docker-build-api
	$(MAKE) -C apps/fred-evaluation-backend docker-build-worker

##@ Help

.PHONY: help
help: ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)
