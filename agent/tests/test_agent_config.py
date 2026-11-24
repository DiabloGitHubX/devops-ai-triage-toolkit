"""Regression tests for agent configuration and Skill loading."""

from pathlib import Path

import pytest

from agent.config import (
    ConfigurationError,
    load_settings,
    load_skill,
)


@pytest.fixture
def config_file(tmp_path):
    """Provide an isolated configuration with synthetic credentials."""

    path = tmp_path / ".env"

    path.write_text(
        "LLM_API_KEY=synthetic-test-key\n",
        encoding="utf-8",
        newline="\n",
    )

    return path


def test_default_configuration(config_file):
    settings = load_settings(
        env_path=config_file,
        environ={},
    )

    assert settings.llm_api_key == "synthetic-test-key"
    assert settings.llm_model == "gemini-3.5-flash-lite"
    assert settings.max_steps == 10
    assert settings.token_budget == 30000
    assert settings.max_llm_calls == 12
    assert settings.max_output_tokens == 2048
    assert settings.llm_timeout == 60
    assert settings.mcp_timeout == 45
    assert settings.max_runtime == 300
    assert settings.default_namespace == "staging"


def test_environment_overrides_file(config_file):
    settings = load_settings(
        env_path=config_file,
        environ={
            "LLM_API_KEY": "environment-test-key",
            "LLM_MODEL": "alternative-model",
            "AGENT_MAX_STEPS": "5",
            "AGENT_DEFAULT_NAMESPACE": "development",
        },
    )

    assert settings.llm_api_key == "environment-test-key"
    assert settings.llm_model == "alternative-model"
    assert settings.max_steps == 5
    assert settings.default_namespace == "development"


def test_api_key_excluded_from_repr(config_file):
    settings = load_settings(
        env_path=config_file,
        environ={},
    )

    assert settings.llm_api_key not in repr(settings)


def test_missing_api_key(tmp_path):
    path = tmp_path / ".env"

    path.write_text(
        "",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ConfigurationError):
        load_settings(
            env_path=path,
            environ={},
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LLM_API_KEY", ""),
        ("LLM_API_KEY", "invalid key"),
        ("LLM_API_KEY", "invalid\nkey"),
        ("LLM_BASE_URL", "http://example.invalid/v1/"),
        ("LLM_BASE_URL", "not-a-url"),
        ("LLM_BASE_URL", "https://user:password@example.invalid/"),
        ("LLM_BASE_URL", "https://example.invalid/?key=secret"),
        ("LLM_BASE_URL", "https://example.invalid/#fragment"),
        ("LLM_BASE_URL", "https://example.invalid:99999/"),
        ("LLM_MODEL", ""),
        ("LLM_MODEL", "invalid model"),
        ("LLM_MODEL", "x" * 257),
        ("AGENT_MAX_STEPS", "0"),
        ("AGENT_MAX_STEPS", "51"),
        ("AGENT_MAX_STEPS", "invalid"),
        ("AGENT_TOKEN_BUDGET", "4095"),
        ("AGENT_TOKEN_BUDGET", "200001"),
        ("AGENT_MAX_LLM_CALLS", "0"),
        ("AGENT_MAX_LLM_CALLS", "61"),
        ("AGENT_MAX_OUTPUT_TOKENS", "255"),
        ("AGENT_MAX_OUTPUT_TOKENS", "8193"),
        ("AGENT_LLM_TIMEOUT", "4"),
        ("AGENT_LLM_TIMEOUT", "121"),
        ("AGENT_MCP_TIMEOUT", "4"),
        ("AGENT_MCP_TIMEOUT", "121"),
        ("AGENT_MAX_RUNTIME", "29"),
        ("AGENT_MAX_RUNTIME", "901"),
        ("AGENT_DEFAULT_NAMESPACE", ""),
        ("AGENT_DEFAULT_NAMESPACE", "INVALID"),
        ("AGENT_DEFAULT_NAMESPACE", "../staging"),
        ("AGENT_DEFAULT_NAMESPACE", "-staging"),
        ("AGENT_DEFAULT_NAMESPACE", "staging-"),
        ("AGENT_DEFAULT_NAMESPACE", "x" * 64),
    ],
)
def test_invalid_configuration(config_file, name, value):
    with pytest.raises(ConfigurationError):
        load_settings(
            env_path=config_file,
            environ={name: value},
        )


def test_output_limit_must_be_smaller_than_budget(config_file):
    with pytest.raises(ConfigurationError):
        load_settings(
            env_path=config_file,
            environ={
                "AGENT_TOKEN_BUDGET": "4096",
                "AGENT_MAX_OUTPUT_TOKENS": "4096",
            },
        )


@pytest.mark.parametrize(
    ("name", "value", "attribute", "expected"),
    [
        ("AGENT_MAX_STEPS", "1", "max_steps", 1),
        ("AGENT_MAX_STEPS", "50", "max_steps", 50),
        ("AGENT_TOKEN_BUDGET", "4096", "token_budget", 4096),
        ("AGENT_TOKEN_BUDGET", "200000", "token_budget", 200000),
        ("AGENT_MAX_LLM_CALLS", "1", "max_llm_calls", 1),
        ("AGENT_MAX_LLM_CALLS", "60", "max_llm_calls", 60),
        ("AGENT_MAX_OUTPUT_TOKENS", "256", "max_output_tokens", 256),
        ("AGENT_MAX_OUTPUT_TOKENS", "8192", "max_output_tokens", 8192),
        ("AGENT_LLM_TIMEOUT", "5", "llm_timeout", 5),
        ("AGENT_LLM_TIMEOUT", "120", "llm_timeout", 120),
        ("AGENT_MCP_TIMEOUT", "5", "mcp_timeout", 5),
        ("AGENT_MCP_TIMEOUT", "120", "mcp_timeout", 120),
        ("AGENT_MAX_RUNTIME", "30", "max_runtime", 30),
        ("AGENT_MAX_RUNTIME", "900", "max_runtime", 900),
    ],
)
def test_configuration_boundaries(
    config_file,
    name,
    value,
    attribute,
    expected,
):
    settings = load_settings(
        env_path=config_file,
        environ={name: value},
    )

    assert getattr(settings, attribute) == expected


def test_valid_custom_skill(tmp_path):
    """Verify deterministic Skill loading across operating systems."""

    path = tmp_path / "SKILL.md"
    content = "# Test Skill\n\nRead-only diagnostics.\n"

    path.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )

    assert load_skill(path).strip() == content.strip()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_skill_supports_platform_line_endings(tmp_path, newline):
    """Verify support for both Unix and Windows line endings."""

    path = tmp_path / "SKILL.md"

    lines = [
        "# Test Skill",
        "",
        "Read-only diagnostics.",
    ]

    content = newline.join(lines) + newline

    # Write exact bytes to avoid operating-system newline conversion.
    path.write_bytes(content.encode("utf-8"))

    loaded = load_skill(path)

    assert loaded.splitlines() == lines


def test_repository_skill_loads(config_file):
    settings = load_settings(
        env_path=config_file,
        environ={},
    )

    content = load_skill(settings.skill_path)

    assert settings.skill_path.is_file()
    assert isinstance(settings.skill_path, Path)
    assert "k8s-triage" in content
    assert len(content.splitlines()) < 300


def test_missing_skill(tmp_path):
    with pytest.raises(ConfigurationError):
        load_skill(tmp_path / "missing.md")


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"   \n",
        b"\xff\xfe\xfd",
        b"x" * 32769,
        b"line\n" * 300,
    ],
)
def test_invalid_skill(tmp_path, content):
    path = tmp_path / "SKILL.md"

    path.write_bytes(content)

    with pytest.raises(ConfigurationError):
        load_skill(path)
