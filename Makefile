SHELL := bash

.DEFAULT_GOAL := help

.PHONY: help env kubeconfig clean

help:
	@echo "DevOps AI Triage Toolkit"
	@echo ""
	@echo "Available targets:"
	@echo "  make env         Create or refresh the local environment"
	@echo "  make kubeconfig  Refresh restricted Kubernetes credentials"
	@echo "  make clean       Delete the local kind environment"
	@echo "  make help        Show available commands"

env:
	bash scripts/setup.sh

kubeconfig:
	bash scripts/generate-kubeconfig.sh

clean:
	bash scripts/cleanup.sh