PROJECT_NAME=fred-deepeval-cli
PY_PACKAGE=fred_deepeval_cli

include scripts/makefiles/python-vars.mk

include scripts/makefiles/python-deps.mk
include scripts/makefiles/python-code-quality.mk
include scripts/makefiles/python-test.mk
include scripts/makefiles/python-clean.mk
include scripts/makefiles/help.mk

ENV_FILE := $(ROOT_DIR)/config/.env
export ENV_FILE 

.PHONY: cli
cli: dev ## Run the external EvalTrace CLI
	VIRTUAL_ENV= $(UV) run python -m fred_deepeval_cli.cli.main --help

.PHONY: eval-dev
eval-dev: ## Install dev + DeepEval dependencies
	VIRTUAL_ENV= $(UV) sync --extra dev --extra eval

.PHONY: score
score: eval-dev ## Evaluate one Fred agent turn: trace + structural checks + DeepEval
	@if [ -z "$(BASE_URL)" ] || [ -z "$(AGENT_ID)" ] || [ -z "$(INPUT)" ] || [ -z "$(SESSION_ID)" ] || [ -z "$(USER_ID)" ]; then \
		echo "Usage: make score BASE_URL=http://127.0.0.1:8000/fred/agents/v2 AGENT_ID=fred.test.assistant INPUT='echo bonjour' SESSION_ID=eval-001 USER_ID=alice [TEAM_ID=my-team] [PRESET=auto]"; \
		exit 1; \
	fi
	VIRTUAL_ENV= $(UV) run python -m fred_deepeval_cli.cli.main score \
		--base-url "$(BASE_URL)" \
		--agent-id "$(AGENT_ID)" \
		--input "$(INPUT)" \
		--session-id "$(SESSION_ID)" \
		--user-id "$(USER_ID)" \
		$(if $(TEAM_ID),--team-id "$(TEAM_ID)",) \
		$(if $(ACCESS_TOKEN),--access-token "$(ACCESS_TOKEN)",) \
		$(if $(SEARCH_POLICY),--search-policy "$(SEARCH_POLICY)",) \
		$(if $(PROFILE),--profile "$(PROFILE)",)

.PHONY: rag-scenarios
rag-scenarios: eval-dev ## Run the RAG scenario campaign against fred.github.rag_expert
	@if [ -z "$(BASE_URL)" ]; then \
		echo "Usage: make rag-scenarios BASE_URL=http://127.0.0.1:8000/fred/agents/v2 [AGENT_ID=fred.github.rag_expert] [USER_ID=alice] [TEAM_ID=my-team] [DATASET=tests/rag_dataset.json]"; \
		exit 1; \
	fi
	VIRTUAL_ENV= $(UV) run python scripts/run_rag_scenarios.py \
		--base-url "$(BASE_URL)" \
		--agent-id "$(or $(AGENT_ID),fred.github.rag_expert)" \
		--user-id "$(or $(USER_ID),alice)" \
		$(if $(TEAM_ID),--team-id "$(TEAM_ID)",) \
		$(if $(ACCESS_TOKEN),--access-token "$(ACCESS_TOKEN)",) \
		$(if $(SEARCH_POLICY),--search-policy "$(SEARCH_POLICY)",) \
		$(if $(DATASET),--dataset "$(DATASET)",) \
		$(if $(USE_TEMPORAL),--use-temporal,) \
		$(if $(TEMPORAL_SERVER),--temporal-server "$(TEMPORAL_SERVER)",)

.PHONY: sql-scenarios
sql-scenarios: eval-dev ## Run the SQL scenario campaign against fred.github.sql_expert
	@if [ -z "$(BASE_URL)" ]; then \
		echo "Usage: make sql-scenarios BASE_URL=http://127.0.0.1:8000/fred/agents/v2 [USER_ID=alice] [TEAM_ID=my-team]"; \
		exit 1; \
	fi
	VIRTUAL_ENV= $(UV) run python scripts/run_sql_scenarios.py \
		--base-url "$(BASE_URL)" \
		--agent-id "fred.github.sql_expert" \
		--user-id "$(or $(USER_ID),alice)" \
		$(if $(TEAM_ID),--team-id "$(TEAM_ID)",) \
		$(if $(ACCESS_TOKEN),--access-token "$(ACCESS_TOKEN)",)