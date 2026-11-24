"""Configuration for the read-only DevOps triage MCP server."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_LOG_TAIL = 100
MAX_LOG_TAIL = 500

NAMESPACE_PATTERN = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")


class ConfigurationError(ValueError):
    """Raised when server configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable MCP server runtime configuration."""

    allowed_namespaces: frozenset[str]
    kubeconfig_path: Path
    kubeconfig_context: str
    ci_fixtures_dir: Path
    max_pods: int
    max_events: int
    max_response_bytes: int
    max_ci_file_bytes: int
    request_timeout: int
    log_level: str


def _parse_int(
    name: str,
    value: str,
    minimum: int,
    maximum: int,
) -> int:
    """Parse and validate a bounded integer setting."""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"{name} must be an integer") from None

    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")

    return parsed


def _parse_namespaces(value: str) -> frozenset[str]:
    """Parse a comma-separated namespace allowlist."""

    namespaces = frozenset(
        namespace.strip() for namespace in value.split(",") if namespace.strip()
    )

    if not namespaces:
        raise ConfigurationError("ALLOWED_NAMESPACES must not be empty")

    for namespace in namespaces:
        if not NAMESPACE_PATTERN.fullmatch(namespace):
            raise ConfigurationError("ALLOWED_NAMESPACES contains an invalid namespace")

    return namespaces


def _resolve_path(value: str) -> Path:
    """Resolve paths relative to the project root."""

    if not value.strip():
        raise ConfigurationError("Configured path must not be empty")

    path = Path(value).expanduser()

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path.resolve()


def load_settings() -> Settings:
    """Load configuration without modifying process environment."""

    file_values = dotenv_values(PROJECT_ROOT / ".env")

    def get(name: str, default: str) -> str:
        if name in os.environ:
            return os.environ[name]

        value = file_values.get(name)

        return default if value is None else value

    log_level = get("LOG_LEVEL", "INFO").strip().upper()

    if log_level not in {
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        raise ConfigurationError("LOG_LEVEL must be INFO, WARNING, ERROR, or CRITICAL")

    kubeconfig_context = get(
        "KUBECONFIG_CONTEXT",
        "triage-reader",
    ).strip()

    if not kubeconfig_context:
        raise ConfigurationError("KUBECONFIG_CONTEXT must not be empty")

    return Settings(
        allowed_namespaces=_parse_namespaces(get("ALLOWED_NAMESPACES", "staging")),
        kubeconfig_path=_resolve_path(get("KUBECONFIG_PATH", ".runtime/kubeconfig")),
        kubeconfig_context=kubeconfig_context,
        ci_fixtures_dir=_resolve_path(get("CI_FIXTURES_DIR", "fixtures/ci")),
        max_pods=_parse_int(
            "MAX_PODS",
            get("MAX_PODS", "100"),
            1,
            100,
        ),
        max_events=_parse_int(
            "MAX_EVENTS",
            get("MAX_EVENTS", "50"),
            1,
            50,
        ),
        max_response_bytes=_parse_int(
            "MAX_RESPONSE_BYTES",
            get("MAX_RESPONSE_BYTES", "32768"),
            1024,
            32768,
        ),
        max_ci_file_bytes=_parse_int(
            "MAX_CI_FILE_BYTES",
            get("MAX_CI_FILE_BYTES", "1048576"),
            1024,
            1048576,
        ),
        request_timeout=_parse_int(
            "K8S_REQUEST_TIMEOUT",
            get("K8S_REQUEST_TIMEOUT", "10"),
            1,
            30,
        ),
        log_level=log_level,
    )
