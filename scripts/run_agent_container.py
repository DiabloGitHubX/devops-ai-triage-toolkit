"""Launch the hardened diagnostic agent container."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agent.config import ConfigurationError, load_settings, load_skill

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def error(message: str) -> int:
    """Report a safe operator-facing error."""
    print(f"[ERROR] {message}", file=sys.stderr)
    return 1


def runtime_environment(settings) -> dict[str, str]:
    """Return only approved, validated agent configuration."""

    return {
        "LLM_API_KEY": settings.llm_api_key,
        "LLM_BASE_URL": settings.llm_base_url,
        "LLM_MODEL": settings.llm_model,
        "AGENT_MAX_STEPS": str(settings.max_steps),
        "AGENT_TOKEN_BUDGET": str(settings.token_budget),
        "AGENT_MAX_LLM_CALLS": str(settings.max_llm_calls),
        "AGENT_MAX_OUTPUT_TOKENS": str(settings.max_output_tokens),
        "AGENT_LLM_TIMEOUT": str(settings.llm_timeout),
        "AGENT_MCP_TIMEOUT": str(settings.mcp_timeout),
        "AGENT_MAX_RUNTIME": str(settings.max_runtime),
        "AGENT_DEFAULT_NAMESPACE": settings.default_namespace,
    }


def main(argv: list[str] | None = None) -> int:
    """Validate configuration and launch Docker without a shell."""

    arguments = list(sys.argv[1:] if argv is None else argv)

    if not arguments:
        arguments = ["--help"]

    os.chdir(PROJECT_ROOT)

    image = os.environ.get(
        "AGENT_IMAGE",
        "devops-ai-triage-toolkit:local",
    )

    network = os.environ.get(
        "DOCKER_NETWORK",
        "kind",
    )

    kubeconfig = Path(
        os.environ.get(
            "CONTAINER_KUBECONFIG_PATH",
            ".runtime/kubeconfig.container",
        )
    ).resolve()

    env_file = Path(
        os.environ.get(
            "AGENT_ENV_FILE",
            ".env",
        )
    ).resolve()

    if not kubeconfig.is_file():
        return error(
            "Restricted container kubeconfig not found. Run make docker-kubeconfig."
        )

    if not env_file.is_file():
        return error(
            "Agent environment file not found. Configure .env using .env.example."
        )

    try:
        settings = load_settings(env_path=env_file)
        load_skill(settings.skill_path)
    except (ConfigurationError, OSError):
        return error(
            "Invalid agent configuration or Skill. "
            "Check configuration against .env.example."
        )

    if settings.default_namespace != "staging":
        return error("The container deployment is restricted to the staging namespace.")

    approved = runtime_environment(settings)

    environment = os.environ.copy()
    environment.update(approved)

    command = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--network",
        network,
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=64m",
        "--memory",
        "512m",
        "--cpus",
        "1.0",
        "--pids-limit",
        "128",
    ]

    # Docker receives variable names only.
    # Their values are inherited from the subprocess environment.
    for name in approved:
        command.extend(["--env", name])

    command.extend(
        [
            "--env",
            "KUBECONFIG_PATH=/run/credentials/kubeconfig",
            "--env",
            "KUBECONFIG_CONTEXT=triage-reader",
            "--env",
            "ALLOWED_NAMESPACES=staging",
            "--env",
            "CI_FIXTURES_DIR=/app/fixtures/ci",
            "--mount",
            (
                f"type=bind,source={kubeconfig.as_posix()},"
                "target=/run/credentials/kubeconfig,readonly"
            ),
            image,
            *arguments,
        ]
    )

    print(
        "[INFO] Validated agent configuration",
        file=sys.stderr,
    )

    print(
        "[INFO] Starting hardened agent container",
        file=sys.stderr,
    )

    try:
        result = subprocess.run(
            command,
            env=environment,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return error("Docker executable not found.")
    except OSError:
        return error("Unable to launch Docker.")
    except KeyboardInterrupt:
        return 130

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
