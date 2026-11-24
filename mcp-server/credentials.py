"""Validation of restricted token-only Kubernetes credentials."""

import base64
import binascii
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

MAX_KUBECONFIG_BYTES = 65536

TOP_LEVEL_FIELDS = {
    "apiVersion",
    "kind",
    "clusters",
    "users",
    "contexts",
    "current-context",
}


class CredentialError(RuntimeError):
    """A sanitized restricted credential configuration error."""


def _require_mapping(
    value: Any,
    expected_fields: set[str],
    section: str,
) -> dict:
    """Require an exact mapping structure."""

    if not isinstance(value, dict):
        raise CredentialError(f"Invalid kubeconfig {section} structure.")

    if set(value) != expected_fields:
        raise CredentialError(f"Unsupported or missing kubeconfig {section} fields.")

    return value


def _require_string(
    value: Any,
    section: str,
) -> str:
    """Require a nonempty string without control characters."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise CredentialError(f"Invalid kubeconfig {section} value.")

    return value


def _single_entry(
    entries: Any,
    section: str,
    data_key: str,
) -> dict:
    """Require exactly one named configuration entry."""

    if not isinstance(entries, list) or len(entries) != 1:
        raise CredentialError(f"Kubeconfig must contain exactly one {section}.")

    entry = _require_mapping(
        entries[0],
        {"name", data_key},
        section,
    )

    _require_string(
        entry["name"],
        f"{section} name",
    )

    return entry


def _validate_server(value: Any) -> None:
    """Require an HTTPS Kubernetes API endpoint."""

    server = _require_string(
        value,
        "server endpoint",
    )

    try:
        parsed = urlsplit(server)

        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path in {"", "/"}
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and not any(char.isspace() for char in server)
            and "\\" not in server
        )

    except ValueError:
        valid = False

    if not valid:
        raise CredentialError("Kubeconfig requires a valid HTTPS API endpoint.")


def _validate_ca(value: Any) -> None:
    """Require embedded base64-encoded CA certificate data."""

    encoded = _require_string(
        value,
        "certificate authority",
    )

    try:
        decoded = base64.b64decode(
            encoded,
            validate=True,
        )
    except (ValueError, binascii.Error):
        raise CredentialError("Invalid embedded certificate authority data.") from None

    if (
        b"-----BEGIN CERTIFICATE-----" not in decoded
        or b"-----END CERTIFICATE-----" not in decoded
    ):
        raise CredentialError(
            "Embedded certificate authority data must contain a PEM certificate."
        )


def validate_kubeconfig(
    data: Any,
    expected_context: str,
    allowed_namespaces: frozenset[str],
) -> dict:
    """Validate and reconstruct a restricted kubeconfig."""

    root = _require_mapping(
        data,
        TOP_LEVEL_FIELDS,
        "top-level",
    )

    if root["apiVersion"] != "v1" or root["kind"] != "Config":
        raise CredentialError("Unsupported kubeconfig version or kind.")

    if root["current-context"] != expected_context:
        raise CredentialError("Unexpected kubeconfig current context.")

    cluster_entry = _single_entry(
        root["clusters"],
        "cluster",
        "cluster",
    )

    user_entry = _single_entry(
        root["users"],
        "user",
        "user",
    )

    context_entry = _single_entry(
        root["contexts"],
        "context",
        "context",
    )

    cluster = _require_mapping(
        cluster_entry["cluster"],
        {"server", "certificate-authority-data"},
        "cluster configuration",
    )

    user = _require_mapping(
        user_entry["user"],
        {"token"},
        "authentication",
    )

    context = _require_mapping(
        context_entry["context"],
        {"cluster", "user", "namespace"},
        "context configuration",
    )

    _validate_server(cluster["server"])
    _validate_ca(cluster["certificate-authority-data"])

    token = _require_string(
        user["token"],
        "bearer token",
    )

    if any(char.isspace() for char in token):
        raise CredentialError("Invalid kubeconfig bearer token.")

    namespace = _require_string(
        context["namespace"],
        "namespace",
    )

    if namespace not in allowed_namespaces:
        raise CredentialError("Kubeconfig namespace is outside the allowlist.")

    if (
        context_entry["name"] != expected_context
        or context["cluster"] != cluster_entry["name"]
        or context["user"] != user_entry["name"]
    ):
        raise CredentialError("Invalid kubeconfig context references.")

    # Reconstruct only the explicitly supported fields.
    # Never pass arbitrary parsed YAML directly to the SDK.
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": expected_context,
        "clusters": [
            {
                "name": cluster_entry["name"],
                "cluster": {
                    "server": cluster["server"],
                    "certificate-authority-data": (
                        cluster["certificate-authority-data"]
                    ),
                },
            }
        ],
        "users": [
            {
                "name": user_entry["name"],
                "user": {"token": token},
            }
        ],
        "contexts": [
            {
                "name": expected_context,
                "context": {
                    "cluster": cluster_entry["name"],
                    "user": user_entry["name"],
                    "namespace": namespace,
                },
            }
        ],
    }


def load_restricted_kubeconfig(
    path: Path,
    expected_context: str,
    allowed_namespaces: frozenset[str],
) -> dict:
    """Read and validate bounded kubeconfig data."""

    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_KUBECONFIG_BYTES + 1)

    except FileNotFoundError:
        raise CredentialError(
            "Restricted kubeconfig is missing. Run make env or make kubeconfig."
        ) from None

    except OSError:
        raise CredentialError("Unable to read restricted kubeconfig.") from None

    if len(raw) > MAX_KUBECONFIG_BYTES:
        raise CredentialError("Restricted kubeconfig exceeds the file size limit.")

    try:
        data = yaml.safe_load(raw.decode("utf-8"))

    except (UnicodeError, yaml.YAMLError, RecursionError):
        raise CredentialError("Restricted kubeconfig contains invalid YAML.") from None

    return validate_kubeconfig(
        data=data,
        expected_context=expected_context,
        allowed_namespaces=allowed_namespaces,
    )
