"""Shared fixtures for isolated MCP server tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from config import Settings
from kubernetes import client
from kubernetes_tools import KubernetesTools

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """Create an isolated CI fixture directory."""

    directory = tmp_path / "fixtures" / "ci"
    directory.mkdir(parents=True)

    return directory


@pytest.fixture
def settings(
    tmp_path: Path,
    fixture_dir: Path,
) -> Settings:
    """Provide deterministic settings without real credentials."""

    return Settings(
        allowed_namespaces=frozenset({"staging"}),
        kubeconfig_path=tmp_path / "kubeconfig",
        kubeconfig_context="triage-reader",
        ci_fixtures_dir=fixture_dir,
        max_pods=100,
        max_events=50,
        max_response_bytes=32768,
        max_ci_file_bytes=1048576,
        request_timeout=10,
        log_level="INFO",
    )


@pytest.fixture
def real_ci_fixture_dir() -> Path:
    """Locate the committed synthetic CI fixtures."""

    return PROJECT_ROOT / "fixtures" / "ci"


@pytest.fixture
def mock_core_api() -> MagicMock:
    """Provide a mocked Kubernetes CoreV1Api client."""

    return MagicMock(spec=client.CoreV1Api)


@pytest.fixture
def kubernetes_tools(
    settings: Settings,
    mock_core_api: MagicMock,
) -> KubernetesTools:
    """Create Kubernetes tools without network access."""

    return KubernetesTools(
        settings=settings,
        core_api=mock_core_api,
    )
