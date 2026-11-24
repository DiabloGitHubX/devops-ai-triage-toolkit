"""Validated configuration for the read-only triage agent."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SKILL_PATH = PROJECT_ROOT / "skills" / "k8s-triage" / "SKILL.md"

DEFAULT_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"

MAX_SKILL_BYTES = 32 * 1024

NAMESPACE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class ConfigurationError(RuntimeError):
    """A sanitized agent configuration error."""


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Immutable configuration for an investigation."""

    llm_base_url: str
    llm_api_key: str = field(repr=False)
    llm_model: str

    max_steps: int
    token_budget: int
    max_llm_calls: int
    max_output_tokens: int

    llm_timeout: int
    mcp_timeout: int
    max_runtime: int

    default_namespace: str

    skill_path: Path


def _parse_int(
    values: Mapping[str, str | None],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Read an integer within a supported range."""

    raw = values.get(key, str(default))

    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        raise ConfigurationError(f"{key} must be an integer.") from None

    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{key} must be between {minimum} and {maximum}.")

    return value


def _validate_base_url(value: str) -> str:
    """Require a valid HTTPS provider endpoint."""

    if not value or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise ConfigurationError("LLM_BASE_URL must be a valid HTTPS endpoint.")

    try:
        parsed = urlsplit(value)

        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and "\\" not in value
        )

        port = parsed.port

        if port is not None and not 1 <= port <= 65535:
            valid = False

    except ValueError:
        valid = False

    if not valid:
        raise ConfigurationError("LLM_BASE_URL must be a valid HTTPS endpoint.")

    return value.rstrip("/") + "/"


def _validate_model(value: str) -> str:
    """Reject empty or malformed model identifiers."""

    if (
        not value
        or len(value) > 256
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise ConfigurationError("LLM_MODEL must be a non-empty model identifier.")

    return value


def _validate_namespace(value: str) -> str:
    """Validate the default Kubernetes namespace."""

    if not NAMESPACE_PATTERN.fullmatch(value):
        raise ConfigurationError(
            "AGENT_DEFAULT_NAMESPACE must be a valid Kubernetes namespace."
        )

    return value


def load_settings(
    env_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> AgentSettings:
    """Load agent settings with environment-variable precedence."""

    config_path = env_path if env_path is not None else PROJECT_ROOT / ".env"

    environment = os.environ if environ is None else environ

    try:
        file_values = dotenv_values(
            config_path,
            interpolate=False,
        )
    except (OSError, UnicodeError):
        raise ConfigurationError("Unable to read agent configuration.") from None

    values = {
        **file_values,
        **environment,
    }

    api_key = values.get("LLM_API_KEY") or ""

    if not api_key or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in api_key
    ):
        raise ConfigurationError("LLM_API_KEY is missing or invalid.")

    base_url = _validate_base_url(
        values.get(
            "LLM_BASE_URL",
            DEFAULT_LLM_BASE_URL,
        )
        or ""
    )

    model = _validate_model(
        values.get(
            "LLM_MODEL",
            DEFAULT_LLM_MODEL,
        )
        or ""
    )

    max_steps = _parse_int(
        values,
        "AGENT_MAX_STEPS",
        default=10,
        minimum=1,
        maximum=50,
    )

    token_budget = _parse_int(
        values,
        "AGENT_TOKEN_BUDGET",
        default=30000,
        minimum=4096,
        maximum=200000,
    )

    max_llm_calls = _parse_int(
        values,
        "AGENT_MAX_LLM_CALLS",
        default=12,
        minimum=1,
        maximum=60,
    )

    max_output_tokens = _parse_int(
        values,
        "AGENT_MAX_OUTPUT_TOKENS",
        default=2048,
        minimum=256,
        maximum=8192,
    )

    if max_output_tokens >= token_budget:
        raise ConfigurationError(
            "AGENT_MAX_OUTPUT_TOKENS must be smaller than AGENT_TOKEN_BUDGET."
        )

    llm_timeout = _parse_int(
        values,
        "AGENT_LLM_TIMEOUT",
        default=60,
        minimum=5,
        maximum=120,
    )

    mcp_timeout = _parse_int(
        values,
        "AGENT_MCP_TIMEOUT",
        default=45,
        minimum=5,
        maximum=120,
    )

    max_runtime = _parse_int(
        values,
        "AGENT_MAX_RUNTIME",
        default=300,
        minimum=30,
        maximum=900,
    )

    default_namespace = _validate_namespace(
        values.get(
            "AGENT_DEFAULT_NAMESPACE",
            "staging",
        )
        or ""
    )

    return AgentSettings(
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model=model,
        max_steps=max_steps,
        token_budget=token_budget,
        max_llm_calls=max_llm_calls,
        max_output_tokens=max_output_tokens,
        llm_timeout=llm_timeout,
        mcp_timeout=mcp_timeout,
        max_runtime=max_runtime,
        default_namespace=default_namespace,
        skill_path=SKILL_PATH,
    )


def load_skill(path: Path = SKILL_PATH) -> str:
    """Load bounded UTF-8 diagnostic instructions."""

    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_SKILL_BYTES + 1)

    except OSError:
        raise ConfigurationError("Unable to read the triage Skill.") from None

    if len(raw) > MAX_SKILL_BYTES:
        raise ConfigurationError("The triage Skill exceeds the supported size limit.")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigurationError("The triage Skill is not valid UTF-8.") from None

    if not content.strip():
        raise ConfigurationError("The triage Skill is empty.")

    if len(content.splitlines()) >= 300:
        raise ConfigurationError("The triage Skill must contain fewer than 300 lines.")

    return content
