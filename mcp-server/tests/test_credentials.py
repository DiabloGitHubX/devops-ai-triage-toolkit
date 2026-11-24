"""Security tests for restricted Kubernetes credential initialization."""

import base64
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from config import Settings
from credentials import (
    MAX_KUBECONFIG_BYTES,
    CredentialError,
    load_restricted_kubeconfig,
    validate_kubeconfig,
)
from kubernetes_tools import KubernetesToolError, KubernetesTools

EXPECTED_CONTEXT = "triage-reader"
ALLOWED_NAMESPACES = frozenset({"staging"})

SYNTHETIC_TOKEN = "synthetic-test-token-not-a-real-credential"

SYNTHETIC_CA = base64.b64encode(
    b"-----BEGIN CERTIFICATE-----\n"
    b"SYNTHETIC_TEST_CERTIFICATE\n"
    b"-----END CERTIFICATE-----\n"
).decode("ascii")


@pytest.fixture
def valid_kubeconfig() -> dict:
    """Return a synthetic restricted kubeconfig."""

    return {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": EXPECTED_CONTEXT,
        "clusters": [
            {
                "name": "test-cluster",
                "cluster": {
                    "server": "https://127.0.0.1:6443",
                    "certificate-authority-data": SYNTHETIC_CA,
                },
            }
        ],
        "users": [
            {
                "name": "triage-reader",
                "user": {
                    "token": SYNTHETIC_TOKEN,
                },
            }
        ],
        "contexts": [
            {
                "name": EXPECTED_CONTEXT,
                "context": {
                    "cluster": "test-cluster",
                    "user": "triage-reader",
                    "namespace": "staging",
                },
            }
        ],
    }


def validate(data: object) -> dict:
    """Validate using the expected test security policy."""

    return validate_kubeconfig(
        data=data,
        expected_context=EXPECTED_CONTEXT,
        allowed_namespaces=ALLOWED_NAMESPACES,
    )


def write_kubeconfig(path: Path, data: dict) -> None:
    """Write synthetic credentials to an isolated test file."""

    path.write_text(
        yaml.safe_dump(data),
        encoding="utf-8",
    )


# ============================================================
# Valid restricted configuration
# ============================================================


def test_valid_restricted_kubeconfig(
    valid_kubeconfig: dict,
) -> None:
    result = validate(valid_kubeconfig)

    assert result == valid_kubeconfig
    assert result is not valid_kubeconfig
    assert result["users"] is not valid_kubeconfig["users"]

    assert set(result["users"][0]["user"]) == {"token"}


def test_validation_does_not_modify_input(
    valid_kubeconfig: dict,
) -> None:
    original = deepcopy(valid_kubeconfig)

    validate(valid_kubeconfig)

    assert valid_kubeconfig == original


def test_load_valid_kubeconfig(
    valid_kubeconfig: dict,
    tmp_path: Path,
) -> None:
    path = tmp_path / "kubeconfig"

    write_kubeconfig(path, valid_kubeconfig)

    result = load_restricted_kubeconfig(
        path,
        EXPECTED_CONTEXT,
        ALLOWED_NAMESPACES,
    )

    assert result == valid_kubeconfig


# ============================================================
# Unsupported authentication mechanisms
# ============================================================


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "exec",
            {
                "command": "synthetic-command",
                "apiVersion": "client.authentication.k8s.io/v1",
            },
        ),
        (
            "auth-provider",
            {"name": "synthetic-provider"},
        ),
        ("client-certificate", "/synthetic/certificate"),
        ("client-certificate-data", "synthetic-certificate"),
        ("client-key", "/synthetic/private-key"),
        ("client-key-data", "synthetic-private-key"),
        ("tokenFile", "/synthetic/token"),
        ("username", "synthetic-admin"),
        ("password", "synthetic-password"),
        ("as", "system:admin"),
        ("as-groups", ["system:masters"]),
        ("as-user-extra", {"example": ["value"]}),
    ],
)
def test_unsupported_authentication_fields_are_rejected(
    valid_kubeconfig: dict,
    field: str,
    value: object,
) -> None:
    valid_kubeconfig["users"][0]["user"][field] = value

    with pytest.raises(
        CredentialError,
        match="authentication fields",
    ):
        validate(valid_kubeconfig)


@pytest.mark.parametrize(
    "token",
    [
        "",
        None,
        123,
        True,
        [],
        {},
        " token",
        "token ",
        "token\nvalue",
        "token value",
        "token\x00value",
    ],
)
def test_invalid_bearer_token_is_rejected(
    valid_kubeconfig: dict,
    token: object,
) -> None:
    valid_kubeconfig["users"][0]["user"]["token"] = token

    with pytest.raises(
        CredentialError,
        match="bearer token",
    ):
        validate(valid_kubeconfig)


# ============================================================
# TLS and API endpoint validation
# ============================================================


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("insecure-skip-tls-verify", True),
        ("insecure-skip-tls-verify", False),
        ("certificate-authority", "/synthetic/ca.pem"),
        ("proxy-url", "http://127.0.0.1:8080"),
        ("tls-server-name", "unexpected-host"),
    ],
)
def test_unsupported_cluster_fields_are_rejected(
    valid_kubeconfig: dict,
    field: str,
    value: object,
) -> None:
    valid_kubeconfig["clusters"][0]["cluster"][field] = value

    with pytest.raises(
        CredentialError,
        match="cluster configuration fields",
    ):
        validate(valid_kubeconfig)


@pytest.mark.parametrize(
    "server",
    [
        "http://127.0.0.1:6443",
        "ftp://127.0.0.1",
        "https://",
        "https://user:password@127.0.0.1",
        "https://127.0.0.1?query=value",
        "https://127.0.0.1#fragment",
        "https://127.0.0.1/unexpected/path",
        "https://127.0.0.1:99999",
        "https://127.0.0.1:0",
        "https://invalid host",
        r"https://example.com\unexpected",
    ],
)
def test_invalid_api_endpoint_is_rejected(
    valid_kubeconfig: dict,
    server: str,
) -> None:
    valid_kubeconfig["clusters"][0]["cluster"]["server"] = server

    with pytest.raises(
        CredentialError,
        match="HTTPS API endpoint",
    ):
        validate(valid_kubeconfig)


@pytest.mark.parametrize(
    "ca_data",
    [
        "",
        None,
        "not-valid-base64!",
        base64.b64encode(b"not a PEM certificate").decode("ascii"),
    ],
)
def test_invalid_ca_data_is_rejected(
    valid_kubeconfig: dict,
    ca_data: object,
) -> None:
    valid_kubeconfig["clusters"][0]["cluster"]["certificate-authority-data"] = ca_data

    with pytest.raises(CredentialError):
        validate(valid_kubeconfig)


# ============================================================
# Configuration structure and namespace restrictions
# ============================================================


@pytest.mark.parametrize(
    "section",
    ["clusters", "users", "contexts"],
)
@pytest.mark.parametrize(
    "entry_count",
    [0, 2],
)
def test_multiple_or_missing_entries_are_rejected(
    valid_kubeconfig: dict,
    section: str,
    entry_count: int,
) -> None:
    entry = valid_kubeconfig[section][0]

    valid_kubeconfig[section] = [deepcopy(entry) for _ in range(entry_count)]

    with pytest.raises(
        CredentialError,
        match="exactly one",
    ):
        validate(valid_kubeconfig)


@pytest.mark.parametrize(
    "namespace",
    ["default", "kube-system", "production", "*"],
)
def test_unauthorized_context_namespace_is_rejected(
    valid_kubeconfig: dict,
    namespace: str,
) -> None:
    valid_kubeconfig["contexts"][0]["context"]["namespace"] = namespace

    with pytest.raises(
        CredentialError,
        match="outside the allowlist",
    ):
        validate(valid_kubeconfig)


@pytest.mark.parametrize(
    "field",
    ["cluster", "user"],
)
def test_invalid_context_reference_is_rejected(
    valid_kubeconfig: dict,
    field: str,
) -> None:
    valid_kubeconfig["contexts"][0]["context"][field] = "unexpected-reference"

    with pytest.raises(
        CredentialError,
        match="context references",
    ):
        validate(valid_kubeconfig)


def test_unexpected_current_context_is_rejected(
    valid_kubeconfig: dict,
) -> None:
    valid_kubeconfig["current-context"] = "admin"

    with pytest.raises(
        CredentialError,
        match="current context",
    ):
        validate(valid_kubeconfig)


def test_unknown_top_level_field_is_rejected(
    valid_kubeconfig: dict,
) -> None:
    valid_kubeconfig["extensions"] = []

    with pytest.raises(
        CredentialError,
        match="top-level fields",
    ):
        validate(valid_kubeconfig)


@pytest.mark.parametrize(
    "data",
    [None, [], "invalid", 123, {}],
)
def test_invalid_root_structure_is_rejected(
    data: object,
) -> None:
    with pytest.raises(CredentialError):
        validate(data)


# ============================================================
# Bounded file loading and safe YAML parsing
# ============================================================


def test_missing_kubeconfig(tmp_path: Path) -> None:
    with pytest.raises(
        CredentialError,
        match="kubeconfig is missing",
    ):
        load_restricted_kubeconfig(
            tmp_path / "missing-kubeconfig",
            EXPECTED_CONTEXT,
            ALLOWED_NAMESPACES,
        )


def test_oversized_kubeconfig_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "kubeconfig"

    path.write_bytes(b"a" * (MAX_KUBECONFIG_BYTES + 1))

    with pytest.raises(
        CredentialError,
        match="file size limit",
    ):
        load_restricted_kubeconfig(
            path,
            EXPECTED_CONTEXT,
            ALLOWED_NAMESPACES,
        )


@pytest.mark.parametrize(
    "content",
    [
        b"invalid: [yaml",
        b"\xff\xfe\xff",
        b"!!python/object:example.UnsafeObject {}",
    ],
)
def test_invalid_or_unsafe_yaml_is_rejected(
    tmp_path: Path,
    content: bytes,
) -> None:
    path = tmp_path / "kubeconfig"

    path.write_bytes(content)

    with pytest.raises(
        CredentialError,
        match="invalid YAML",
    ):
        load_restricted_kubeconfig(
            path,
            EXPECTED_CONTEXT,
            ALLOWED_NAMESPACES,
        )


# ============================================================
# Kubernetes SDK initialization boundary
# ============================================================


def test_unsafe_credentials_never_reach_sdk(
    settings: Settings,
    valid_kubeconfig: dict,
) -> None:
    valid_kubeconfig["users"][0]["user"]["exec"] = {
        "command": "synthetic-command",
    }

    write_kubeconfig(
        settings.kubeconfig_path,
        valid_kubeconfig,
    )

    with patch(
        "kubernetes_tools.kube_config.new_client_from_config_dict"
    ) as sdk_loader:
        with pytest.raises(
            KubernetesToolError,
            match="authentication fields",
        ):
            KubernetesTools(settings)

        sdk_loader.assert_not_called()


def test_missing_credentials_never_reach_sdk(
    settings: Settings,
) -> None:
    with patch(
        "kubernetes_tools.kube_config.new_client_from_config_dict"
    ) as sdk_loader:
        with pytest.raises(
            KubernetesToolError,
            match="kubeconfig is missing",
        ):
            KubernetesTools(settings)

        sdk_loader.assert_not_called()


def test_valid_credentials_use_dictionary_loader(
    settings: Settings,
    valid_kubeconfig: dict,
) -> None:
    write_kubeconfig(
        settings.kubeconfig_path,
        valid_kubeconfig,
    )

    api_client = MagicMock()
    api_client.configuration.verify_ssl = True

    with (
        patch(
            "kubernetes_tools.kube_config.new_client_from_config_dict",
            return_value=api_client,
        ) as sdk_loader,
        patch("kubernetes_tools.client.AuthenticationV1Api") as auth_factory,
        patch("kubernetes_tools.client.CoreV1Api") as core_factory,
    ):
        review = auth_factory.return_value.create_self_subject_review.return_value

        review.status.user_info.username = "system:serviceaccount:staging:triage-reader"

        review.status.user_info.groups = [
            "system:serviceaccounts",
            "system:serviceaccounts:staging",
            "system:authenticated",
        ]

        tools = KubernetesTools(settings)

        sdk_loader.assert_called_once_with(
            config_dict=valid_kubeconfig,
            context=EXPECTED_CONTEXT,
            persist_config=False,
        )

        core_factory.assert_called_once_with(api_client)

        assert tools.core_api is core_factory.return_value

        tools.close()

        api_client.close.assert_called_once()


@pytest.mark.parametrize(
    ("identity", "groups"),
    [
        ("system:admin", ["system:masters"]),
        (
            "system:serviceaccount:default:triage-reader",
            [],
        ),
        (
            "system:serviceaccount:staging:default",
            [],
        ),
        (
            "system:serviceaccount:staging:triage-reader",
            ["system:masters"],
        ),
    ],
)
def test_unexpected_identity_is_rejected_and_client_closed(
    settings: Settings,
    valid_kubeconfig: dict,
    identity: str,
    groups: list[str],
) -> None:
    write_kubeconfig(
        settings.kubeconfig_path,
        valid_kubeconfig,
    )

    api_client = MagicMock()
    api_client.configuration.verify_ssl = True

    with (
        patch(
            "kubernetes_tools.kube_config.new_client_from_config_dict",
            return_value=api_client,
        ),
        patch("kubernetes_tools.client.AuthenticationV1Api") as auth_factory,
        patch("kubernetes_tools.client.CoreV1Api") as core_factory,
    ):
        review = auth_factory.return_value.create_self_subject_review.return_value

        review.status.user_info.username = identity
        review.status.user_info.groups = groups

        with pytest.raises(KubernetesToolError):
            KubernetesTools(settings)

        core_factory.assert_not_called()
        api_client.close.assert_called_once()


def test_disabled_sdk_tls_is_rejected(
    settings: Settings,
    valid_kubeconfig: dict,
) -> None:
    write_kubeconfig(
        settings.kubeconfig_path,
        valid_kubeconfig,
    )

    api_client = MagicMock()
    api_client.configuration.verify_ssl = False

    with (
        patch(
            "kubernetes_tools.kube_config.new_client_from_config_dict",
            return_value=api_client,
        ),
        patch("kubernetes_tools.client.AuthenticationV1Api") as auth_factory,
    ):
        with pytest.raises(
            KubernetesToolError,
            match="Insecure Kubernetes TLS",
        ):
            KubernetesTools(settings)

        auth_factory.assert_not_called()
        api_client.close.assert_called_once()
