"""Structural regression tests for the triage skill."""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SKILL_PATH = PROJECT_ROOT / "skills" / "k8s-triage" / "SKILL.md"


@pytest.fixture
def skill_content() -> str:
    """Load the triage skill instructions."""

    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_frontmatter(skill_content: str) -> None:
    """Require valid skill metadata."""

    lines = skill_content.splitlines()

    assert lines[0] == "---"

    end = lines.index("---", 1)

    metadata = yaml.safe_load("\n".join(lines[1:end]))

    assert metadata["name"] == "k8s-triage"
    assert isinstance(metadata["description"], str)
    assert metadata["description"].strip()


def test_skill_line_limit(skill_content: str) -> None:
    """Enforce the assignment's line-count requirement."""

    assert len(skill_content.splitlines()) < 300


@pytest.mark.parametrize(
    "tool",
    [
        "list_pods",
        "describe_pod",
        "get_pod_logs",
        "list_events",
        "get_ci_log",
    ],
)
def test_required_mcp_tools(
    skill_content: str,
    tool: str,
) -> None:
    """Require references to every diagnostic MCP tool."""

    assert tool in skill_content


@pytest.mark.parametrize(
    "scenario",
    [
        "ImagePullBackOff",
        "CrashLoopBackOff",
        "OOMKilled",
        "Pending",
        "Application or Test Failure",
        "Build or Infrastructure Failure",
        "Configuration or Deployment Validation Failure",
    ],
)
def test_required_diagnostic_branches(
    skill_content: str,
    scenario: str,
) -> None:
    """Require the supported diagnostic scenarios."""

    assert scenario in skill_content


def test_diagnosis_section_order(
    skill_content: str,
) -> None:
    """Require the assignment's diagnosis format."""

    sections = [
        "### Symptom",
        "### Evidence",
        "### Root cause",
        "### Suggested fix",
        "### Confidence",
    ]

    lines = skill_content.splitlines()

    for section in sections:
        assert lines.count(section) == 1

    positions = [lines.index(section) for section in sections]

    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "rule",
    [
        "namespace allowlist",
        "Never execute",
        "untrusted diagnostic data",
        "Unknown — insufficient evidence",
        "execution and token budgets",
        "Redact sensitive values",
    ],
)
def test_required_safety_rules(
    skill_content: str,
    rule: str,
) -> None:
    """Detect accidental removal of key safety instructions."""

    assert rule in skill_content


def test_deterministic_helper_exists(
    skill_content: str,
) -> None:
    """Require the referenced offline helper."""

    relative_path = "scripts/extract_ci_error.py"

    assert relative_path in skill_content

    assert (SKILL_PATH.parent / relative_path).is_file()
