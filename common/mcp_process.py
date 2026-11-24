"""Shared MCP subprocess configuration for clients and tests."""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from mcp import StdioServerParameters

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PATH = PROJECT_ROOT / "mcp-server" / "server.py"

MCP_ENV_KEYS = frozenset(
    {
        "ALLOWED_NAMESPACES",
        "KUBECONFIG_PATH",
        "KUBECONFIG_CONTEXT",
        "CI_FIXTURES_DIR",
        "MAX_PODS",
        "MAX_EVENTS",
        "MAX_RESPONSE_BYTES",
        "MAX_CI_FILE_BYTES",
        "K8S_REQUEST_TIMEOUT",
        "LOG_LEVEL",
    }
)


def build_mcp_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Forward only explicitly supported MCP configuration."""

    environment = {key: os.environ[key] for key in MCP_ENV_KEYS if key in os.environ}

    if overrides:
        unsupported = set(overrides) - MCP_ENV_KEYS

        if unsupported:
            raise ValueError("Unsupported MCP environment override")

        environment.update(overrides)

    return environment


def build_server_parameters(
    overrides: Mapping[str, str] | None = None,
) -> StdioServerParameters:
    """Configure the official MCP stdio client subprocess."""

    return StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(PROJECT_ROOT),
        env=build_mcp_environment(overrides),
    )
