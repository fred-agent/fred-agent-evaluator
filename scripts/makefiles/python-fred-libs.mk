# fred's libraries: `pypi` (the locked, published ones) or `local` (your fred
# checkout at FRED_REPO, which has no default): fred-deployment-factory's
# docs/LOCAL-DEVELOPMENT.md, "Work on unreleased fred".
#
# Needs, from the including Makefile:
# - FRED_LOCAL_BASE: the target that installs this project's whole environment
# - FRED_LOCAL_PACKAGES: the fred packages under $(FRED_REPO)/libs it uses

FRED_LIBS ?= pypi
FRED_REPO ?=
# Only the install targets sync, so a `make dev-local` overlay survives every `uv run`.
export UV_NO_SYNC := 1

# For `docker build`: the switch, and the checkout as the `fred` build context.
FRED_DOCKER_ARGS = --build-arg FRED_LIBS=$(FRED_LIBS) $(if $(filter local,$(FRED_LIBS)),--build-context fred=$(FRED_REPO))

##@ Fred libraries

.PHONY: fred-repo-check
fred-repo-check:
	@test -n "$(FRED_REPO)" || { printf '%s\n' \
		"FRED_REPO is not set: give the path of YOUR fred checkout, e.g." \
		"    export FRED_REPO=/path/to/your/fred" \
		"(without it, make dev and FRED_LIBS=pypi use the released fred)" >&2; exit 1; }
	@test -d "$(FRED_REPO)/libs" || { echo "FRED_REPO=$(FRED_REPO) is not a fred checkout (no libs/): set FRED_REPO to the path of your fred checkout." >&2; exit 1; }

.PHONY: fred-docker-check
fred-docker-check:
ifeq ($(FRED_LIBS),local)
	@$(MAKE) --no-print-directory fred-repo-check
	@echo "fred's libraries from $(FRED_REPO) ($$(git -C $(FRED_REPO) describe --always --dirty))"
else ifneq ($(FRED_LIBS),pypi)
	$(error FRED_LIBS must be pypi or local, not '$(FRED_LIBS)')
endif

.PHONY: dev-local
dev-local: fred-repo-check $(FRED_LOCAL_BASE) ## Swap in fred's libraries from your fred checkout at FRED_REPO (editable)
	VIRTUAL_ENV=$(VENV) $(UV) pip install $(foreach p,$(FRED_LOCAL_PACKAGES),--editable "$(FRED_REPO)/libs/$(p)")
	@echo "fred's libraries from $(FRED_REPO) ($$(git -C $(FRED_REPO) describe --always --dirty)). \`make dev-pypi\` goes back."

.PHONY: dev-pypi
dev-pypi: ## Go back to the locked, published fred libraries after dev-local
	rm -f $(TARGET)/.compiled $(TARGET)/.full-env
	$(MAKE) --no-print-directory $(FRED_LOCAL_BASE)
