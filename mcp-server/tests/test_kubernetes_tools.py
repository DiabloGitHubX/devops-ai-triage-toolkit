"""Tests for Kubernetes diagnostic tools using mocked API clients."""

import json
from unittest.mock import MagicMock

import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from kubernetes_tools import KubernetesToolError, KubernetesTools
from safety import SafetyError

# ============================================================
# Namespace authorization before diagnostic API access
# ============================================================


@pytest.mark.parametrize(
    "namespace",
    [
        "default",
        "kube-system",
        "production",
        "",
        "*",
        "STAGING",
    ],
)
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("list_pods", {}),
        ("describe_pod", {"pod_name": "orders-api"}),
        ("get_pod_logs", {"pod_name": "orders-api"}),
        ("list_events", {}),
    ],
)
def test_unauthorized_namespace_never_reaches_api(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
    namespace: str,
    tool_name: str,
    arguments: dict,
) -> None:
    tool = getattr(kubernetes_tools, tool_name)

    with pytest.raises(SafetyError, match="allowlist"):
        tool(namespace=namespace, **arguments)

    assert not mock_core_api.mock_calls


# ============================================================
# Invalid parameters must not reach the API
# ============================================================


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("describe_pod", {"pod_name": "../orders-api"}),
        ("get_pod_logs", {"pod_name": "../orders-api"}),
        (
            "get_pod_logs",
            {
                "pod_name": "orders-api",
                "container": "../container",
            },
        ),
        (
            "get_pod_logs",
            {
                "pod_name": "orders-api",
                "tail_lines": 501,
            },
        ),
        (
            "get_pod_logs",
            {
                "pod_name": "orders-api",
                "tail_lines": True,
            },
        ),
        (
            "get_pod_logs",
            {
                "pod_name": "orders-api",
                "previous": "true",
            },
        ),
        ("list_pods", {"label_selector": "app=orders\n"}),
        ("list_pods", {"label_selector": "a" * 1025}),
        ("list_events", {"involved_object": "../pod"}),
    ],
)
def test_invalid_arguments_never_reach_api(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
    tool_name: str,
    arguments: dict,
) -> None:
    tool = getattr(kubernetes_tools, tool_name)

    with pytest.raises(SafetyError):
        tool(namespace="staging", **arguments)

    assert not mock_core_api.mock_calls


# ============================================================
# Authorized pod listing
# ============================================================


def test_list_pods_empty_namespace(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    mock_core_api.list_namespaced_pod.return_value = client.V1PodList(
        items=[],
        metadata=client.V1ListMeta(),
    )

    result = kubernetes_tools.list_pods("staging")

    assert result["namespace"] == "staging"
    assert result["count"] == 0
    assert result["pods"] == []
    assert result["truncated"] is False

    mock_core_api.list_namespaced_pod.assert_called_once()

    arguments = mock_core_api.list_namespaced_pod.call_args.kwargs

    assert arguments["namespace"] == "staging"
    assert arguments["limit"] == 100
    assert arguments["_request_timeout"] == 10


def test_list_pods_forwards_label_selector(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    mock_core_api.list_namespaced_pod.return_value = client.V1PodList(
        items=[],
        metadata=client.V1ListMeta(),
    )

    selector = "app.kubernetes.io/name=orders-api"

    kubernetes_tools.list_pods(
        namespace="staging",
        label_selector=selector,
    )

    arguments = mock_core_api.list_namespaced_pod.call_args.kwargs

    assert arguments["label_selector"] == selector


def test_list_pods_reports_incomplete_page(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    mock_core_api.list_namespaced_pod.return_value = client.V1PodList(
        items=[],
        metadata=client.V1ListMeta(
            _continue="synthetic-continuation-token",
        ),
    )

    result = kubernetes_tools.list_pods("staging")

    assert result["truncated"] is True


# ============================================================
# Bounded log retrieval
# ============================================================


def test_get_pod_logs_default_parameters(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    logs = "ERROR: DATABASE_URL is missing"

    mock_core_api.read_namespaced_pod_log.return_value = logs

    result = kubernetes_tools.get_pod_logs(
        namespace="staging",
        pod_name="orders-api",
    )

    assert result["logs"] == logs
    assert result["requested_tail_lines"] == 100
    assert result["previous"] is False
    assert result["truncated"] is False

    mock_core_api.read_namespaced_pod_log.assert_called_once()

    arguments = mock_core_api.read_namespaced_pod_log.call_args.kwargs

    assert arguments["namespace"] == "staging"
    assert arguments["name"] == "orders-api"
    assert arguments["tail_lines"] == 100
    assert arguments["follow"] is False
    assert arguments["previous"] is False
    assert arguments["_request_timeout"] == 10
    assert arguments["limit_bytes"] <= 32768


def test_get_previous_container_logs(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    mock_core_api.read_namespaced_pod_log.return_value = (
        "ERROR: Previous container terminated"
    )

    result = kubernetes_tools.get_pod_logs(
        namespace="staging",
        pod_name="orders-api",
        container="orders-api",
        tail_lines=500,
        previous=True,
    )

    assert result["previous"] is True
    assert result["requested_tail_lines"] == 500

    arguments = mock_core_api.read_namespaced_pod_log.call_args.kwargs

    assert arguments["container"] == "orders-api"
    assert arguments["previous"] is True
    assert arguments["tail_lines"] == 500


def test_large_kubernetes_log_is_truncated(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    error = "ERROR: Required configuration missing"

    logs = ("INFO: Starting application\n" * 1000) + error

    mock_core_api.read_namespaced_pod_log.return_value = logs

    result = kubernetes_tools.get_pod_logs(
        namespace="staging",
        pod_name="orders-api",
    )

    serialized = json.dumps(
        result,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")

    assert result["truncated"] is True
    assert len(serialized) <= 32768
    assert result["logs"].endswith(error)
    assert result["returned_bytes"] <= 16384


# ============================================================
# Sanitized Kubernetes API errors
# ============================================================


@pytest.mark.parametrize(
    "status",
    [400, 401, 403, 404, 429, 500, 503],
)
def test_api_errors_do_not_expose_sensitive_details(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
    status: int,
) -> None:
    sensitive_marker = "SYNTHETIC_SENSITIVE_API_DETAILS"

    error = ApiException(
        status=status,
        reason=sensitive_marker,
    )

    error.body = sensitive_marker

    mock_core_api.list_namespaced_pod.side_effect = error

    with pytest.raises(KubernetesToolError) as captured:
        kubernetes_tools.list_pods("staging")

    message = str(captured.value)

    assert message
    assert sensitive_marker not in message
    assert "Traceback" not in message

    mock_core_api.list_namespaced_pod.assert_called_once()
