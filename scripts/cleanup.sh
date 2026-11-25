
#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

CLUSTER_NAME="${CLUSTER_NAME:-devops-triage}"

echo "[INFO] Checking kind cluster: $CLUSTER_NAME"

EXISTING_CLUSTERS="$(kind get clusters)"

if grep -Fxq "$CLUSTER_NAME" <<< "$EXISTING_CLUSTERS"; then
    echo "[INFO] Deleting kind cluster: $CLUSTER_NAME"

    kind delete cluster --name "$CLUSTER_NAME"
else
    echo "[INFO] Cluster does not exist; skipping deletion"
fi

echo "[INFO] Removing default generated kubeconfigs"

rm -f -- \
    .runtime/kubeconfig \
    .runtime/kubeconfig.container

echo "[INFO] Cleanup completed"
