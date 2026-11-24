"""Tests for MCP server configuration."""

from pathlib import Path
from unittest.mock import MagicMock

from config import Settings
from kubernetes_tools import KubernetesTools


def test_isolated_settings(
    settings: Settings,
    tmp_path: Path,
) -> None:
    """Test settings must not depend on real credentials."""

    assert settings.allowed_namespaces == frozenset({"staging"})
    assert settings.kubeconfig_path == tmp_path / "kubeconfig"
    assert not settings.kubeconfig_path.exists()
    assert settings.kubeconfig_context == "triage-reader"
    assert settings.max_response_bytes == 32768
    assert settings.request_timeout == 10


def test_isolated_fixture_directory(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    """CI test files must use an isolated temporary directory."""

    assert settings.ci_fixtures_dir == fixture_dir
    assert fixture_dir.is_dir()
    assert not list(fixture_dir.iterdir())


def test_committed_ci_fixtures_exist(
    real_ci_fixture_dir: Path,
) -> None:
    """Verify that the expected synthetic fixtures are available."""

    expected = {
        "build-1423.log",
        "build-1424.log",
        "build-1425.log",
    }

    actual = {path.name for path in real_ci_fixture_dir.glob("*.log")}

    assert expected.issubset(actual)


def test_mocked_kubernetes_client(
    kubernetes_tools: KubernetesTools,
    mock_core_api: MagicMock,
) -> None:
    """Dependency injection must avoid real Kubernetes connections."""

    assert kubernetes_tools.core_api is mock_core_api
    assert not mock_core_api.mock_calls

    kubernetes_tools.close()

    assert not mock_core_api.mock_calls
