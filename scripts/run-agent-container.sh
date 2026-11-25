
#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

export AGENT_IMAGE="${AGENT_IMAGE:-devops-ai-triage-toolkit:local}"
export DOCKER_NETWORK="${DOCKER_NETWORK:-kind}"
export CONTAINER_KUBECONFIG_PATH="${CONTAINER_KUBECONFIG_PATH:-.runtime/kubeconfig.container}"
export AGENT_ENV_FILE="${AGENT_ENV_FILE:-.env}"

PYTHON="${PYTHON:-python}"

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] Docker is not installed or not available in PATH" >&2
    exit 1
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[ERROR] Python is required for configuration validation" >&2
    exit 1
fi

if ! docker image inspect "$AGENT_IMAGE" >/dev/null 2>&1; then
    echo "[ERROR] Agent image not found. Run make docker-build." >&2
    exit 1
fi

if ! docker network inspect "$DOCKER_NETWORK" >/dev/null 2>&1; then
    echo "[ERROR] Docker network not found: $DOCKER_NETWORK" >&2
    echo "[ERROR] Run make env first." >&2
    exit 1
fi

if [[ ! -f "$CONTAINER_KUBECONFIG_PATH" ]]; then
    echo "[ERROR] Restricted container kubeconfig not found." >&2
    echo "[ERROR] Run make docker-kubeconfig." >&2
    exit 1
fi

if [[ ! -f "$AGENT_ENV_FILE" ]]; then
    echo "[ERROR] Agent environment file not found." >&2
    echo "[ERROR] Configure .env using .env.example." >&2
    exit 1
fi

if [[ "$#" -eq 0 ]]; then
    set -- --help
fi

echo "[INFO] Agent image: $AGENT_IMAGE" >&2
echo "[INFO] Docker network: $DOCKER_NETWORK" >&2

exec "$PYTHON" -m scripts.run_agent_container "$@"
