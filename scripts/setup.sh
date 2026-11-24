#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

export CLUSTER_NAME="${CLUSTER_NAME:-devops-triage}"
export ADMIN_CONTEXT="kind-${CLUSTER_NAME}"
export TRIAGE_NAMESPACE="staging"
export SERVICE_ACCOUNT="triage-reader"
export KUBECONFIG_PATH="${KUBECONFIG_PATH:-.runtime/kubeconfig}"

CLUSTER_TIMEOUT="${CLUSTER_TIMEOUT:-180s}"

# --------------------------------------------------
# Authorization validation
# --------------------------------------------------

check_permission() {
    local expected="$1"
    local namespace="$2"
    shift 2

    local result
    local exit_code=0

    result="$(
        kubectl --kubeconfig "$KUBECONFIG_PATH" \
            auth can-i "$@" \
            -n "$namespace"
    )" || exit_code=$?

    result="${result//$'\r'/}"

    if [[ "$result" != "$expected" ]]; then
        echo "[ERROR] Authorization check failed: $*" >&2
        echo "[ERROR] Namespace: $namespace" >&2
        echo "[ERROR] Expected: $expected" >&2
        echo "[ERROR] Received: $result" >&2
        echo "[ERROR] Exit code: $exit_code" >&2
        exit 1
    fi

    if [[ "$expected" == "yes" && "$exit_code" -ne 0 ]] ||
       [[ "$expected" == "no" && "$exit_code" -ne 1 ]]; then
        echo "[ERROR] Unexpected authorization exit code" >&2
        exit 1
    fi

    echo "[PASS] $namespace: $* -> $result"
}

# --------------------------------------------------
# Prerequisite validation
# --------------------------------------------------

echo "[INFO] Checking prerequisites"

for command in docker kind kubectl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "[ERROR] Required command not found: $command" >&2
        exit 1
    fi
done

if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker is not running or is inaccessible" >&2
    exit 1
fi

# --------------------------------------------------
# Kubernetes cluster provisioning
# --------------------------------------------------

echo "[INFO] Checking kind cluster: $CLUSTER_NAME"

EXISTING_CLUSTERS="$(kind get clusters)"

if grep -Fxq "$CLUSTER_NAME" <<< "$EXISTING_CLUSTERS"; then
    echo "[INFO] Existing cluster found; reusing it"
else
    echo "[INFO] Creating kind cluster"

    kind create cluster \
        --name "$CLUSTER_NAME" \
        --config env/kind-config.yaml \
        --wait "$CLUSTER_TIMEOUT"
fi

echo "[INFO] Waiting for Kubernetes node readiness"

kubectl --context "$ADMIN_CONTEXT" wait \
    --for=condition=Ready \
    nodes --all \
    --timeout="$CLUSTER_TIMEOUT"

# --------------------------------------------------
# Kubernetes resource deployment
# --------------------------------------------------

echo "[INFO] Applying namespace"

kubectl --context "$ADMIN_CONTEXT" apply \
    -f env/namespace.yaml

echo "[INFO] Applying least-privilege RBAC"

kubectl --context "$ADMIN_CONTEXT" apply \
    -f env/rbac.yaml

echo "[INFO] Deploying intentionally broken workloads"

kubectl --context "$ADMIN_CONTEXT" apply \
    -f env/workloads/

# --------------------------------------------------
# Restricted credential generation
# --------------------------------------------------

echo "[INFO] Generating restricted kubeconfig"

bash scripts/generate-kubeconfig.sh

# --------------------------------------------------
# Authentication validation
# --------------------------------------------------

echo "[INFO] Verifying restricted authentication"

IDENTITY="$(
    kubectl --kubeconfig "$KUBECONFIG_PATH" \
        auth whoami \
        -o jsonpath='{.status.userInfo.username}'
)"

EXPECTED_IDENTITY="system:serviceaccount:${TRIAGE_NAMESPACE}:${SERVICE_ACCOUNT}"

if [[ "$IDENTITY" != "$EXPECTED_IDENTITY" ]]; then
    echo "[ERROR] Unexpected Kubernetes identity" >&2
    echo "[ERROR] Expected: $EXPECTED_IDENTITY" >&2
    echo "[ERROR] Received: $IDENTITY" >&2
    exit 1
fi

echo "[INFO] Authenticated as: $IDENTITY"

# --------------------------------------------------
# Restricted read access validation
# --------------------------------------------------

echo "[INFO] Verifying restricted read access"

kubectl --kubeconfig "$KUBECONFIG_PATH" \
    get pods -n "$TRIAGE_NAMESPACE"

# --------------------------------------------------
# Required permissions
# --------------------------------------------------

echo "[INFO] Verifying required permissions"

check_permission yes "$TRIAGE_NAMESPACE" get pods
check_permission yes "$TRIAGE_NAMESPACE" list pods
check_permission yes "$TRIAGE_NAMESPACE" get pods --subresource=log
check_permission yes "$TRIAGE_NAMESPACE" list events

# --------------------------------------------------
# Forbidden permissions
# --------------------------------------------------

echo "[INFO] Verifying forbidden permissions"

check_permission no "$TRIAGE_NAMESPACE" list secrets
check_permission no "$TRIAGE_NAMESPACE" get secrets
check_permission no "$TRIAGE_NAMESPACE" create pods
check_permission no "$TRIAGE_NAMESPACE" delete pods
check_permission no "$TRIAGE_NAMESPACE" patch pods
check_permission no "$TRIAGE_NAMESPACE" update pods
check_permission no "$TRIAGE_NAMESPACE" watch pods
check_permission no "$TRIAGE_NAMESPACE" get configmaps
check_permission no "$TRIAGE_NAMESPACE" list deployments
check_permission no "$TRIAGE_NAMESPACE" patch deployments
check_permission no "$TRIAGE_NAMESPACE" create pods --subresource=exec
check_permission no "$TRIAGE_NAMESPACE" get pods --subresource=exec
check_permission no "$TRIAGE_NAMESPACE" create pods --subresource=portforward
check_permission no "$TRIAGE_NAMESPACE" get pods --subresource=portforward

# --------------------------------------------------
# Namespace isolation
# --------------------------------------------------

echo "[INFO] Verifying namespace isolation"

check_permission no default list pods
check_permission no kube-system list pods

# --------------------------------------------------
# Setup completion
# --------------------------------------------------

echo "[INFO] Environment setup completed"
echo "[INFO] Workloads are intentionally unhealthy"
echo "[INFO] Failure states may take time to stabilize"
echo "[INFO] Restricted kubeconfig: $KUBECONFIG_PATH"