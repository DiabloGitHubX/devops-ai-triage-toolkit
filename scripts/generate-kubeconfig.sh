
#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

CLUSTER_NAME="${CLUSTER_NAME:-devops-triage}"
ADMIN_CONTEXT="${ADMIN_CONTEXT:-kind-${CLUSTER_NAME}}"
TRIAGE_NAMESPACE="${TRIAGE_NAMESPACE:-staging}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-triage-reader}"
TOKEN_DURATION="${TOKEN_DURATION:-8h}"
KUBECONFIG_MODE="${KUBECONFIG_MODE:-host}"

case "$KUBECONFIG_MODE" in
    host)
        KUBECONFIG_PATH="${KUBECONFIG_PATH:-.runtime/kubeconfig}"
        ;;
    container)
        KUBECONFIG_PATH="${KUBECONFIG_PATH:-.runtime/kubeconfig.container}"
        ;;
    *)
        echo "[ERROR] KUBECONFIG_MODE must be host or container" >&2
        exit 1
        ;;
esac

umask 077

mkdir -p "$(dirname "$KUBECONFIG_PATH")"

echo "[INFO] Discovering Kubernetes API endpoint"

if [[ "$KUBECONFIG_MODE" == "host" ]]; then
    API_SERVER="$(
        kubectl --context "$ADMIN_CONTEXT" config view \
            --minify \
            -o jsonpath='{.clusters[0].cluster.server}'
    )"
else
    CONTROL_PLANE="${CLUSTER_NAME}-control-plane"

    if ! docker inspect \
        --format '{{.State.Running}}' \
        "$CONTROL_PLANE" | grep -qx true; then

        echo "[ERROR] Kind control plane is not running" >&2
        exit 1
    fi

    API_SERVER="https://${CONTROL_PLANE}:6443"
fi

CA_DATA="$(
    kubectl --context "$ADMIN_CONTEXT" config view \
        --minify \
        --raw \
        --flatten \
        -o jsonpath='{.clusters[0].cluster.certificate-authority-data}'
)"

if [[ -z "$API_SERVER" || -z "$CA_DATA" ]]; then
    echo "[ERROR] Unable to discover cluster connection details" >&2
    exit 1
fi

echo "[INFO] Requesting temporary ServiceAccount token"

TOKEN="$(
    kubectl --context "$ADMIN_CONTEXT" create token \
        "$SERVICE_ACCOUNT" \
        --namespace "$TRIAGE_NAMESPACE" \
        --duration "$TOKEN_DURATION"
)"

if [[ -z "$TOKEN" ]]; then
    echo "[ERROR] ServiceAccount token generation failed" >&2
    exit 1
fi

TEMP_CONFIG="$(mktemp "${KUBECONFIG_PATH}.XXXXXX")"

trap 'rm -f "$TEMP_CONFIG"; unset TOKEN' EXIT

cat > "$TEMP_CONFIG" <<EOF
apiVersion: v1
kind: Config

clusters:
  - name: ${CLUSTER_NAME}
    cluster:
      server: ${API_SERVER}
      certificate-authority-data: ${CA_DATA}

users:
  - name: ${SERVICE_ACCOUNT}
    user:
      token: ${TOKEN}

contexts:
  - name: triage-reader
    context:
      cluster: ${CLUSTER_NAME}
      user: ${SERVICE_ACCOUNT}
      namespace: ${TRIAGE_NAMESPACE}

current-context: triage-reader
EOF

chmod 600 "$TEMP_CONFIG"

mv -f "$TEMP_CONFIG" "$KUBECONFIG_PATH"

unset TOKEN

echo "[INFO] Restricted kubeconfig generated"
echo "[INFO] Mode: $KUBECONFIG_MODE"
echo "[INFO] Path: $KUBECONFIG_PATH"
echo "[INFO] API endpoint: $API_SERVER"
echo "[INFO] Namespace: $TRIAGE_NAMESPACE"
echo "[INFO] Requested token duration: $TOKEN_DURATION"
