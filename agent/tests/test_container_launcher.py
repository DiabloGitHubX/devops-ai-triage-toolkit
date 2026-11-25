"""Regression tests for the host-side Docker agent launcher."""

from unittest.mock import Mock

import pytest

from agent.config import ConfigurationError, load_settings
from scripts import run_agent_container as launcher


@pytest.fixture
def runtime_files(tmp_path, monkeypatch):
    """Create isolated runtime configuration with dummy credentials."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_API_KEY=offline-test-placeholder \n"
        'LLM_BASE_URL="https://example.com/v1/"\n'
        "LLM_MODEL=offline-test-model\n"
        "AGENT_MAX_STEPS=10\n"
        "AGENT_TOKEN_BUDGET=30000\n"
        "UNRELATED_SECRET=must-not-be-forwarded\n",
        encoding="utf-8",
    )

    kubeconfig = tmp_path / "kubeconfig.container"
    kubeconfig.write_text(
        "dummy-test-kubeconfig",
        encoding="utf-8",
    )

    for key in launcher.runtime_environment(
        load_settings(env_path=env_file, environ={})
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("AGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv(
        "CONTAINER_KUBECONFIG_PATH",
        str(kubeconfig),
    )
    monkeypatch.setenv("AGENT_IMAGE", "test-agent:local")
    monkeypatch.setenv("DOCKER_NETWORK", "test-network")

    monkeypatch.setattr(
        launcher,
        "PROJECT_ROOT",
        tmp_path,
    )

    monkeypatch.setattr(
        launcher.os,
        "chdir",
        Mock(),
    )

    return env_file, kubeconfig


def test_dotenv_whitespace_is_normalized(runtime_files):
    env_file, _ = runtime_files

    settings = load_settings(
        env_path=env_file,
        environ={},
    )

    assert settings.llm_api_key == "offline-test-placeholder"


def test_quoted_url_is_parsed(runtime_files):
    env_file, _ = runtime_files

    settings = load_settings(
        env_path=env_file,
        environ={},
    )

    assert settings.llm_base_url == "https://example.com/v1/"


def test_environment_allowlist(runtime_files):
    env_file, _ = runtime_files

    settings = load_settings(
        env_path=env_file,
        environ={},
    )

    forwarded = launcher.runtime_environment(settings)

    assert set(forwarded) == {
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "AGENT_MAX_STEPS",
        "AGENT_TOKEN_BUDGET",
        "AGENT_MAX_LLM_CALLS",
        "AGENT_MAX_OUTPUT_TOKENS",
        "AGENT_LLM_TIMEOUT",
        "AGENT_MCP_TIMEOUT",
        "AGENT_MAX_RUNTIME",
        "AGENT_DEFAULT_NAMESPACE",
    }

    assert "UNRELATED_SECRET" not in forwarded


def test_numeric_values_and_defaults(runtime_files):
    env_file, _ = runtime_files

    settings = load_settings(
        env_path=env_file,
        environ={},
    )

    forwarded = launcher.runtime_environment(settings)

    assert forwarded["AGENT_MAX_STEPS"] == "10"
    assert forwarded["AGENT_TOKEN_BUDGET"] == "30000"
    assert forwarded["AGENT_MAX_LLM_CALLS"] == "12"
    assert forwarded["AGENT_MAX_OUTPUT_TOKENS"] == "2048"
    assert forwarded["AGENT_MAX_RUNTIME"] == "300"
    assert forwarded["AGENT_DEFAULT_NAMESPACE"] == "staging"

    assert all(isinstance(value, str) for value in forwarded.values())


def test_invalid_environment_key_remains_rejected(runtime_files):
    env_file, _ = runtime_files

    with pytest.raises(ConfigurationError):
        load_settings(
            env_path=env_file,
            environ={
                "LLM_API_KEY": "invalid key with spaces",
            },
        )


def test_docker_command_security(
    runtime_files,
    monkeypatch,
):
    _, kubeconfig = runtime_files

    run = Mock(return_value=Mock(returncode=0))

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    result = launcher.main(["--ci", "build-1424"])

    assert result == 0

    run.assert_called_once()

    command = run.call_args.args[0]
    options = run.call_args.kwargs

    assert command[:2] == ["docker", "run"]
    assert "--rm" in command
    assert "--init" in command
    assert "--read-only" in command

    assert command[command.index("--user") + 1] == "10001:10001"
    assert command[command.index("--cap-drop") + 1] == "ALL"

    assert command[command.index("--security-opt") + 1] == "no-new-privileges:true"

    assert command[command.index("--memory") + 1] == "512m"
    assert command[command.index("--cpus") + 1] == "1.0"
    assert command[command.index("--pids-limit") + 1] == "128"

    assert command[command.index("--network") + 1] == "test-network"

    mount = command[command.index("--mount") + 1]

    assert mount == (
        f"type=bind,source={kubeconfig.resolve().as_posix()},"
        "target=/run/credentials/kubeconfig,readonly"
    )

    assert "--env-file" not in command
    assert "--privileged" not in command
    assert "ALLOWED_NAMESPACES=staging" in command
    assert "KUBECONFIG_CONTEXT=triage-reader" in command

    assert command[-3:] == [
        "test-agent:local",
        "--ci",
        "build-1424",
    ]

    assert options["shell"] is False
    assert options["check"] is False


def test_secret_absent_from_command_arguments(
    runtime_files,
    monkeypatch,
):
    run = Mock(return_value=Mock(returncode=0))

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 0

    command = run.call_args.args[0]
    environment = run.call_args.kwargs["env"]

    secret = "offline-test-placeholder"

    assert environment["LLM_API_KEY"] == secret

    assert all(secret not in argument for argument in command)

    assert "LLM_API_KEY" in command
    assert "UNRELATED_SECRET" not in command

    assert not any(argument.startswith("UNRELATED_SECRET=") for argument in command)


def test_missing_kubeconfig_rejected(
    runtime_files,
    monkeypatch,
):
    _, kubeconfig = runtime_files
    kubeconfig.unlink()

    run = Mock()

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 1
    run.assert_not_called()


def test_missing_env_file_rejected(
    runtime_files,
    monkeypatch,
):
    env_file, _ = runtime_files
    env_file.unlink()

    run = Mock()

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 1
    run.assert_not_called()


def test_invalid_configuration_rejected(
    runtime_files,
    monkeypatch,
):
    monkeypatch.setenv(
        "LLM_API_KEY",
        "invalid key",
    )

    run = Mock()

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 1
    run.assert_not_called()


def test_non_staging_namespace_rejected(
    runtime_files,
    monkeypatch,
):
    monkeypatch.setenv(
        "AGENT_DEFAULT_NAMESPACE",
        "production",
    )

    run = Mock()

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 1
    run.assert_not_called()


@pytest.mark.parametrize(
    "returncode",
    [0, 1, 2, 3, 125, 137],
)
def test_docker_exit_code_preserved(
    runtime_files,
    monkeypatch,
    returncode,
):
    run = Mock(return_value=Mock(returncode=returncode))

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == returncode


def test_default_arguments_are_help(
    runtime_files,
    monkeypatch,
):
    run = Mock(return_value=Mock(returncode=0))

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main([]) == 0
    assert run.call_args.args[0][-1] == "--help"


def test_missing_docker_executable(
    runtime_files,
    monkeypatch,
):
    run = Mock(side_effect=FileNotFoundError)

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 1


def test_docker_launch_os_error(
    runtime_files,
    monkeypatch,
):
    run = Mock(side_effect=OSError)

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 1


def test_keyboard_interrupt(
    runtime_files,
    monkeypatch,
):
    run = Mock(side_effect=KeyboardInterrupt)

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 130


def test_environment_file_not_modified(
    runtime_files,
    monkeypatch,
):
    env_file, _ = runtime_files
    original = env_file.read_bytes()

    run = Mock(return_value=Mock(returncode=0))

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        run,
    )

    assert launcher.main(["--help"]) == 0
    assert env_file.read_bytes() == original
