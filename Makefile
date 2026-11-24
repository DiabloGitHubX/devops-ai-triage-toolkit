SHELL := bash
.DEFAULT_GOAL := help

PYTHON ?= python

.PHONY: help env kubeconfig mcp mcp-smoke clean

help:
	@echo "Available targets:"
	@echo "  make env         Provision the Kubernetes environment"
	@echo "  make kubeconfig  Refresh restricted Kubernetes credentials"
	@echo "  make mcp         Start the MCP server using stdio"
	@echo "  make mcp-smoke   Run MCP protocol integration tests"
	@echo "  make clean       Remove the local Kubernetes environment"

env:
	bash scripts/setup.sh

kubeconfig:
	bash scripts/generate-kubeconfig.sh

mcp:
	$(PYTHON) mcp-server/server.py

mcp-smoke:
	$(PYTHON) scripts/mcp_smoke_test.py

clean:
	bash scripts/cleanup.sh
