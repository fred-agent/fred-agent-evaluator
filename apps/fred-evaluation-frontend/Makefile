# Fred evaluation application UI, served by Fred's host at /apps/evaluation/.

PORT ?= 5181
OPENAPI := ../fred-evaluation-backend/openapi.json
API_TYPES := src/shared/api/openapi.d.ts

.PHONY: dev run build code-quality code-quality-fix check-api generate-api test clean help

node_modules: package.json package-lock.json
	npm ci --no-audit --no-fund
	@touch $@

dev: node_modules ## Install dependencies from the lockfile

# The host origin this UI accepts messages from; copied from the example once,
# then yours to edit (git-ignored).
public/config.json:
	cp config.example.json $@

run: node_modules | public/config.json ## Serve the UI for Fred's host on PORT (5181)
	npm run dev -- --port $(PORT) --strictPort

build: node_modules ## Build the static bundle into dist/
	npm run build

generate-api: node_modules ## Regenerate the API types from the backend's openapi.json
	npm run -s generate:api

check-api: node_modules ## Fail if the API types lag the backend's openapi.json
	@tmp=$$(mktemp -d); \
	npx openapi-typescript $(OPENAPI) -o $$tmp/openapi.d.ts >/dev/null 2>&1 && \
	cmp -s $$tmp/openapi.d.ts $(API_TYPES); status=$$?; rm -rf $$tmp; \
	if [ $$status -ne 0 ]; then echo "$(API_TYPES) is stale: run 'make generate-api'"; exit 1; fi

code-quality: node_modules check-api ## Toolchain, dependency boundary, types, format, lint
	node scripts/check-toolchain.mjs
	node scripts/check-boundary.mjs
	npm run typecheck
	npm run format:check
	npm run lint

code-quality-fix: node_modules ## Format and apply lint fixes
	npm run format:write
	npm run lint -- --fix

test: node_modules ## Run the unit tests
	npm test

clean: ## Remove build output
	rm -rf dist coverage

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'
