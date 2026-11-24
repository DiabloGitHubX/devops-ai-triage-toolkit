SHELL := bash
.DEFAULT_GOAL := help

PYTHON ?= python
ARGS ?= --help

.PHONY: help env kubeconfig mcp mcp-smoke agent test lint clean

help:
	@echo "Available targets:"
	@echo "  make env         Provision the Kubernetes environment"
	@echo "  make kubeconfig  Refresh restricted Kubernetes credentials"
	@echo "  make mcp         Start the MCP server using stdio"
	@echo "  make mcp-smoke   Run MCP protocol integration tests"
	@echo "  make agent       Run the autonomous diagnostic agent"
	@echo "  make test        Run automated safety and regression tests"
	@echo "  make lint        Check Python linting and formatting"
	@echo "  make clean       Remove the local Kubernetes environment"
	@echo ""
	@echo "Agent examples:"
	@echo '  make agent ARGS="--ci build-1423"'
	@echo '  make agent ARGS="--pod payments-api"'
	@echo '  make agent ARGS="--namespace staging --pod orders-api"'

env:
	bash scripts/setup.sh

kubeconfig:
	bash scripts/generate-kubeconfig.sh

mcp:
	@$(PYTHON) mcp-server/server.py

mcp-smoke:
	$(PYTHON) -m scripts.mcp_smoke_test

agent:
	@$(PYTHON) -m agent $(ARGS)

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check common/ mcp-server/ agent/ scripts/mcp_smoke_test.py skills/k8s-triage/scripts/
	$(PYTHON) -m ruff format --check common/ mcp-server/ agent/ scripts/mcp_smoke_test.py skills/k8s-triage/scripts/

clean:
	bash scripts/cleanup.sh
