"""Unit tests for MCP input validation and safety boundaries."""

import pytest
from safety import (
    SafetyError,
    validate_container_name,
    validate_label_selector,
    validate_namespace,
    validate_resource_name,
    validate_tail_lines,
)

ALLOWED_NAMESPACES = frozenset({"staging"})


# ============================================================
# Namespace authorization
# ============================================================


def test_allowed_namespace() -> None:
    assert (
        validate_namespace(
            "staging",
            ALLOWED_NAMESPACES,
        )
        == "staging"
    )


@pytest.mark.parametrize(
    "namespace",
    [
        "default",
        "kube-system",
        "kube-public",
        "prod",
        "production",
        "dev",
        "",
        "*",
        "STAGING",
        "Staging",
        " staging",
        "staging ",
        "staging\n",
        "../staging",
        "staging/default",
    ],
)
def test_disallowed_namespace(namespace: str) -> None:
    with pytest.raises(SafetyError, match="allowlist"):
        validate_namespace(namespace, ALLOWED_NAMESPACES)


@pytest.mark.parametrize(
    "namespace",
    [None, 123, True, [], {}],
)
def test_invalid_namespace_type(namespace: object) -> None:
    with pytest.raises(SafetyError, match="must be a string"):
        validate_namespace(namespace, ALLOWED_NAMESPACES)


def test_configurable_namespace_allowlist() -> None:
    allowed = frozenset({"staging", "development"})

    assert validate_namespace("staging", allowed) == "staging"
    assert validate_namespace("development", allowed) == "development"

    with pytest.raises(SafetyError, match="allowlist"):
        validate_namespace("production", allowed)


def test_empty_namespace_allowlist_denies_access() -> None:
    with pytest.raises(SafetyError, match="allowlist"):
        validate_namespace("staging", frozenset())


# ============================================================
# Kubernetes resource names
# ============================================================


@pytest.mark.parametrize(
    "name",
    [
        "orders-api",
        "payments-api-7b775b9b67-rznls",
        "analytics-worker",
        "pod.example",
        "a",
        "123",
        "a" * 63,
        ".".join(["a" * 63] * 3 + ["a" * 61]),
    ],
)
def test_valid_resource_name(name: str) -> None:
    assert validate_resource_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../pod",
        "namespace/pod",
        "Pod",
        "pod_name",
        "-pod",
        "pod-",
        ".pod",
        "pod.",
        "pod..example",
        "pod name",
        "pod\nname",
        "a" * 64,
        "a" * 254,
        ".".join(["a" * 63] * 4),
    ],
)
def test_invalid_resource_name(name: str) -> None:
    with pytest.raises(SafetyError, match="Invalid"):
        validate_resource_name(name)


@pytest.mark.parametrize(
    "name",
    [None, 123, True],
)
def test_invalid_resource_name_type(name: object) -> None:
    with pytest.raises(SafetyError, match="must be a string"):
        validate_resource_name(name)


def test_resource_name_error_uses_field_name() -> None:
    with pytest.raises(SafetyError, match="Invalid pod name"):
        validate_resource_name("../pod", field="pod name")


# ============================================================
# Container names
# ============================================================


@pytest.mark.parametrize(
    "name",
    [
        "orders-api",
        "worker",
        "sidecar-1",
        "a",
        "a" * 63,
    ],
)
def test_valid_container_name(name: str) -> None:
    assert validate_container_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Orders",
        "container.name",
        "container_name",
        "../container",
        "container name",
        "-container",
        "container-",
        "a" * 64,
    ],
)
def test_invalid_container_name(name: str) -> None:
    with pytest.raises(SafetyError, match="Invalid container name"):
        validate_container_name(name)


@pytest.mark.parametrize(
    "name",
    [None, 123, True],
)
def test_invalid_container_name_type(name: object) -> None:
    with pytest.raises(SafetyError, match="must be a string"):
        validate_container_name(name)


# ============================================================
# Log retrieval limits
# ============================================================


@pytest.mark.parametrize(
    "tail_lines",
    [1, 50, 100, 499, 500],
)
def test_valid_tail_lines(tail_lines: int) -> None:
    assert validate_tail_lines(tail_lines) == tail_lines


@pytest.mark.parametrize(
    "tail_lines",
    [-100, -1, 0, 501, 1000, 1000000],
)
def test_tail_lines_outside_allowed_range(tail_lines: int) -> None:
    with pytest.raises(SafetyError, match="between 1 and 500"):
        validate_tail_lines(tail_lines)


@pytest.mark.parametrize(
    "tail_lines",
    [
        None,
        True,
        False,
        "100",
        100.0,
        [],
        {},
    ],
)
def test_invalid_tail_lines_type(tail_lines: object) -> None:
    with pytest.raises(SafetyError, match="must be an integer"):
        validate_tail_lines(tail_lines)


# ============================================================
# Kubernetes label selectors
# ============================================================


@pytest.mark.parametrize(
    "selector",
    [
        None,
        "",
        "app=orders-api",
        "app.kubernetes.io/name=payments-api",
        "environment=staging,app=worker",
        "environment in (staging,development)",
        "a" * 1024,
    ],
)
def test_valid_label_selector(selector: str | None) -> None:
    assert validate_label_selector(selector) == selector


def test_oversized_label_selector() -> None:
    with pytest.raises(SafetyError, match="maximum length"):
        validate_label_selector("a" * 1025)


@pytest.mark.parametrize(
    "selector",
    [
        "app=orders\n",
        "app=orders\r",
        "app=orders\t",
        "app=orders\x00",
        "app=orders\x1f",
    ],
)
def test_label_selector_control_characters(selector: str) -> None:
    with pytest.raises(SafetyError, match="control characters"):
        validate_label_selector(selector)


@pytest.mark.parametrize(
    "selector",
    [123, True, [], {}],
)
def test_invalid_label_selector_type(selector: object) -> None:
    with pytest.raises(SafetyError, match="must be a string"):
        validate_label_selector(selector)
