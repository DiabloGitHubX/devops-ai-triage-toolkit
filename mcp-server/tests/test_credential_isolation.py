"""Verify configuration separation and MCP environment minimization."""

import sys
from pathlib import Path

import config
import pytest

from common.mcp_process import (
    MCP_ENV_KEYS,
    SERVER_PATH,
    build_mcp_environment,
    build_server_parameters,
)


@pytest.mark.parametrize(
    "credential_name",
    [
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "DATABASE_URL",
        "UNRELATED_SECRET",
        "KUBECONFIG",
    ],
)
def test_unrelated_credentials_are_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
    credential_name: str,
) -> None:
    monkeypatch.setenv(
        credential_name,
        "synthetic-test-value",
    )

    environment = build_mcp_environment()

    assert credential_name not in environment
    assert set(environment) <= MCP_ENV_KEYS


def test_supported_mcp_settings_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ALLOWED_NAMESPACES",
        "staging,testing",
    )

    monkeypatch.setenv(
        "MAX_PODS",
        "25",
    )

    environment = build_mcp_environment()

    assert environment["ALLOWED_NAMESPACES"] == ("staging,testing")

    assert environment["MAX_PODS"] == "25"


def test_explicit_overrides_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ALLOWED_NAMESPACES",
        "staging",
    )

    environment = build_mcp_environment({"ALLOWED_NAMESPACES": "testing"})

    assert environment["ALLOWED_NAMESPACES"] == "testing"


@pytest.mark.parametrize(
    "unsupported_key",
    [
        "LLM_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "KUBECONFIG",
        "PYTHONPATH",
        "UNRELATED_SETTING",
    ],
)
def test_unsupported_overrides_are_rejected(
    unsupported_key: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported MCP environment override",
    ):
        build_mcp_environment({unsupported_key: "synthetic-value"})


def test_server_parameters_use_restricted_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_API_KEY",
        "synthetic-test-key",
    )

    parameters = build_server_parameters({"ALLOWED_NAMESPACES": "staging"})

    assert parameters.command == sys.executable
    assert parameters.args == [str(SERVER_PATH)]
    assert parameters.env is not None

    assert "LLM_API_KEY" not in parameters.env

    assert parameters.env["ALLOWED_NAMESPACES"] == "staging"

    assert set(parameters.env) <= MCP_ENV_KEYS


@pytest.fixture
def isolated_config_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Prevent local files and inherited settings affecting tests."""

    monkeypatch.setattr(
        config,
        "PROJECT_ROOT",
        tmp_path,
    )

    for key in MCP_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    return tmp_path


def test_mcp_ignores_agent_configuration(
    isolated_config_root: Path,
) -> None:
    (isolated_config_root / ".env").write_text(
        "LLM_API_KEY=synthetic-key\nALLOWED_NAMESPACES=production\nMAX_PODS=5\n",
        encoding="utf-8",
    )

    settings = config.load_settings()

    assert settings.allowed_namespaces == frozenset({"staging"})

    assert settings.max_pods == 100


def test_mcp_loads_dedicated_configuration(
    isolated_config_root: Path,
) -> None:
    (isolated_config_root / ".env.mcp").write_text(
        "ALLOWED_NAMESPACES=staging,testing\nMAX_PODS=25\n",
        encoding="utf-8",
    )

    settings = config.load_settings()

    assert settings.allowed_namespaces == frozenset({"staging", "testing"})

    assert settings.max_pods == 25


def test_environment_overrides_mcp_file(
    isolated_config_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (isolated_config_root / ".env.mcp").write_text(
        "MAX_PODS=25\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MAX_PODS", "50")

    settings = config.load_settings()

    assert settings.max_pods == 50


def test_mcp_does_not_interpolate_unrelated_variables(
    isolated_config_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "UNRELATED_SECRET",
        "production",
    )

    (isolated_config_root / ".env.mcp").write_text(
        "ALLOWED_NAMESPACES=${UNRELATED_SECRET}\n",
        encoding="utf-8",
    )

    with pytest.raises(config.ConfigurationError):
        config.load_settings()
