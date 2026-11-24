"""Shared fixtures for agent regression tests."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.config import AgentSettings
from agent.mcp_client import ToolResult
from agent.tests.helpers import TOOL_SCHEMA


@pytest.fixture
def settings():
    """Provide deterministic settings without real credentials."""

    from pathlib import Path

    return AgentSettings(
        llm_base_url="https://example.invalid/v1/",
        llm_api_key="synthetic-test-key",
        llm_model="mock-model",
        max_steps=10,
        token_budget=20000,
        max_llm_calls=12,
        max_output_tokens=2048,
        llm_timeout=60,
        mcp_timeout=45,
        max_runtime=300,
        default_namespace="staging",
        skill_path=Path("unused-test-skill.md"),
    )


@pytest.fixture
def llm():
    """Provide a mocked asynchronous LLM client."""

    client = MagicMock()
    client.complete = AsyncMock()

    return client


@pytest.fixture
def mcp():
    """Provide a mocked MCP client."""

    client = MagicMock()

    client.tool_names = frozenset({"get_ci_log"})
    client.llm_tools.return_value = [deepcopy(TOOL_SCHEMA)]
    client.validate_arguments.return_value = None

    client.call_tool = AsyncMock(
        return_value=ToolResult(
            success=True,
            payload={
                "job_id": "build-1423",
                "logs": "assert 201 == 400",
            },
        )
    )

    return client
