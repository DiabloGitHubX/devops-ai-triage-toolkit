
SHELL := bash
.DEFAULT_GOAL := help

PYTHON ?= python
ARGS ?= --help

AGENT_IMAGE ?= devops-ai-triage-toolkit:local
PYTHON_IMAGE ?= python:3.12-slim
DOCKER_NETWORK ?= kind
CONTAINER_KUBECONFIG_PATH ?= .runtime/kubeconfig.container
AGENT_ENV_FILE ?= .env

.PHONY: help env kubeconfig mcp mcp-smoke agent eval eval-validate test lint clean docker-build docker-kubeconfig docker-agent

help:
	@echo "Available targets:"
	@echo "  make env                Provision the Kubernetes environment"
	@echo "  make kubeconfig         Refresh restricted host credentials"
	@echo "  make mcp                Start the MCP server using stdio"
	@echo "  make mcp-smoke          Run MCP protocol integration tests"
	@echo "  make agent              Run the autonomous diagnostic agent"
	@echo "  make eval               Run the full live agent evaluation"
	@echo "  make eval-validate      Validate evaluation cases without LLM requests"
	@echo "  make test               Run automated safety and regression tests"
	@echo "  make lint               Check Python linting and formatting"
	@echo "  make docker-build       Build the agent container image"
	@echo "  make docker-kubeconfig  Generate restricted container credentials"
	@echo "  make docker-agent       Run the hardened containerized agent"
	@echo "  make clean              Remove the local Kubernetes environment"
	@echo ""
	@echo "Agent examples:"
	@echo '  make agent ARGS="--ci build-1423"'
	@echo '  make agent ARGS="--pod payments-api"'
	@echo '  make agent ARGS="--namespace staging --pod orders-api"'
	@echo ""
	@echo "Docker examples:"
	@echo "  make docker-build"
	@echo "  make docker-kubeconfig"
	@echo '  make docker-agent ARGS="--pod payments-api"'
	@echo '  make docker-agent ARGS="--ci build-1423"'
	@echo ""
	@echo "Evaluation examples:"
	@echo "  make eval-validate"
	@echo "  make eval"
	@echo ""
	@echo "Note: make eval makes live LLM requests and saves evaluation reports."

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

eval:
	@$(PYTHON) -m agent.eval

eval-validate:
	@$(PYTHON) -m agent.eval --validate-only

test:
	$(PYTHON) -m pytest -q


lint:
	$(PYTHON) -m ruff check common/ mcp-server/ agent/ scripts/mcp_smoke_test.py scripts/run_agent_container.py skills/k8s-triage/scripts/
	$(PYTHON) -m ruff format --check common/ mcp-server/ agent/ scripts/mcp_smoke_test.py scripts/run_agent_container.py skills/k8s-triage/scripts/


docker-build:
	docker build --build-arg "PYTHON_IMAGE=$(PYTHON_IMAGE)" --file agent/Dockerfile --tag "$(AGENT_IMAGE)" .

docker-kubeconfig:
	KUBECONFIG_MODE=container KUBECONFIG_PATH="$(CONTAINER_KUBECONFIG_PATH)" bash scripts/generate-kubeconfig.sh

docker-agent:
	@AGENT_IMAGE="$(AGENT_IMAGE)" DOCKER_NETWORK="$(DOCKER_NETWORK)" CONTAINER_KUBECONFIG_PATH="$(CONTAINER_KUBECONFIG_PATH)" AGENT_ENV_FILE="$(AGENT_ENV_FILE)" PYTHON="$(PYTHON)" bash scripts/run-agent-container.sh $(ARGS)

clean:
	bash scripts/cleanup.sh
