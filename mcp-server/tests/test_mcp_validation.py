"""MCP protocol boundary validation and authorization tests."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from common.mcp_process import build_server_parameters

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def server_parameters(
    tmp_path: Path,
) -> StdioServerParameters:
    """Start an isolated server without Kubernetes credentials."""

    missing_config = tmp_path / "missing-kubeconfig"

    assert not missing_config.exists()

    return build_server_parameters(
        {
            "KUBECONFIG_PATH": str(missing_config),
            "KUBECONFIG_CONTEXT": "triage-reader",
            "ALLOWED_NAMESPACES": "staging",
            "CI_FIXTURES_DIR": str(PROJECT_ROOT / "fixtures" / "ci"),
            "LOG_LEVEL": "WARNING",
        }
    )


TOOL_TIMEOUT = timedelta(seconds=30)

EXPECTED_TOOLS = {
    "list_pods",
    "describe_pod",
    "get_pod_logs",
    "list_events",
    "get_ci_log",
}

BASE_LOG_ARGUMENTS = {
    "namespace": "staging",
    "pod_name": "orders-api",
}


def error_message(result: Any) -> str:
    """Extract the textual MCP error response."""

    return "\n".join(item.text for item in result.content if item.type == "text")


async def expect_rejection(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    expected_message: str,
) -> None:
    """Verify rejection before Kubernetes initialization."""

    result = await session.call_tool(
        name,
        arguments=arguments,
        read_timeout_seconds=TOOL_TIMEOUT,
    )

    message = error_message(result)

    assert result.isError, f"Invalid request accepted: {name} {arguments}"

    assert expected_message.lower() in message.lower(), f"Unexpected error: {message}"

    assert "kubeconfig is missing" not in message.lower()
    assert "Traceback" not in message


def test_mcp_tool_schemas(tmp_path: Path) -> None:
    """Verify tool discovery and published argument constraints."""

    async def run() -> None:
        async with (
            stdio_client(server_parameters(tmp_path)) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            discovered = await session.list_tools()

            tools = {tool.name: tool for tool in discovered.tools}

            assert set(tools) == EXPECTED_TOOLS

            for tool in tools.values():
                assert tool.description
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.destructiveHint is False

            schema = tools["get_pod_logs"].inputSchema
            properties = schema["properties"]

            tail = properties["tail_lines"]

            assert tail["type"] == "integer"
            assert tail["minimum"] == 1
            assert tail["maximum"] == 500
            assert tail["default"] == 100

            assert properties["previous"]["type"] == "boolean"
            assert properties["previous"]["default"] is False

            assert set(schema["required"]) == {
                "namespace",
                "pod_name",
            }

            ci_schema = tools["get_ci_log"].inputSchema

            assert ci_schema["properties"]["failing_section_only"]["type"] == "boolean"

    asyncio.run(run())


def test_mcp_rejects_invalid_argument_types(
    tmp_path: Path,
) -> None:
    """Reject incorrectly typed arguments at the MCP boundary."""

    cases = [
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "tail_lines": "100"},
            "tail_lines",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "tail_lines": True},
            "tail_lines",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "tail_lines": 100.0},
            "tail_lines",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "tail_lines": 0},
            "tail_lines",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "tail_lines": 501},
            "tail_lines",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "tail_lines": None},
            "tail_lines",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "previous": "true"},
            "previous",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "previous": 1},
            "previous",
        ),
        (
            "get_pod_logs",
            {**BASE_LOG_ARGUMENTS, "previous": None},
            "previous",
        ),
        (
            "get_ci_log",
            {
                "job_id": "build-1423",
                "failing_section_only": "false",
            },
            "failing_section_only",
        ),
        (
            "get_ci_log",
            {
                "job_id": "build-1423",
                "failing_section_only": 1,
            },
            "failing_section_only",
        ),
        (
            "list_pods",
            {"namespace": 123},
            "namespace",
        ),
        (
            "list_pods",
            {
                "namespace": "staging",
                "label_selector": True,
            },
            "label_selector",
        ),
        (
            "describe_pod",
            {
                "namespace": "staging",
                "pod_name": 123,
            },
            "pod_name",
        ),
        (
            "get_pod_logs",
            {
                **BASE_LOG_ARGUMENTS,
                "container": 123,
            },
            "container",
        ),
        (
            "list_events",
            {
                "namespace": "staging",
                "involved_object": True,
            },
            "involved_object",
        ),
        (
            "get_ci_log",
            {"job_id": 1423},
            "job_id",
        ),
        (
            "list_pods",
            {},
            "namespace",
        ),
    ]

    async def run() -> None:
        async with (
            stdio_client(server_parameters(tmp_path)) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            for name, arguments, expected in cases:
                await expect_rejection(
                    session,
                    name,
                    arguments,
                    expected,
                )

    asyncio.run(run())


def test_mcp_authorizes_namespace_before_connection(
    tmp_path: Path,
) -> None:
    """Reject unauthorized namespaces before loading credentials."""

    cases = [
        (
            "list_pods",
            {"namespace": "kube-system"},
        ),
        (
            "describe_pod",
            {
                "namespace": "default",
                "pod_name": "example",
            },
        ),
        (
            "get_pod_logs",
            {
                "namespace": "production",
                "pod_name": "example",
            },
        ),
        (
            "list_events",
            {"namespace": "kube-system"},
        ),
    ]

    async def run() -> None:
        async with (
            stdio_client(server_parameters(tmp_path)) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            for name, arguments in cases:
                await expect_rejection(
                    session,
                    name,
                    arguments,
                    "allowlist",
                )

    asyncio.run(run())


def test_valid_log_tail_boundaries(
    tmp_path: Path,
) -> None:
    """Accept valid integer bounds before credential initialization."""

    async def run() -> None:
        async with (
            stdio_client(server_parameters(tmp_path)) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            for tail_lines in (1, 100, 500):
                result = await session.call_tool(
                    "get_pod_logs",
                    arguments={
                        **BASE_LOG_ARGUMENTS,
                        "tail_lines": tail_lines,
                        "previous": False,
                    },
                    read_timeout_seconds=TOOL_TIMEOUT,
                )

                assert result.isError

                assert "kubeconfig is missing" in error_message(result).lower()

    asyncio.run(run())


def test_valid_ci_requests_without_kubernetes(
    tmp_path: Path,
) -> None:
    """Ensure valid CI requests remain independent of Kubernetes."""

    async def run() -> None:
        async with (
            stdio_client(server_parameters(tmp_path)) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            for failing_section_only in (True, False):
                result = await session.call_tool(
                    "get_ci_log",
                    arguments={
                        "job_id": "build-1423",
                        "failing_section_only": (failing_section_only),
                    },
                    read_timeout_seconds=TOOL_TIMEOUT,
                )

                assert not result.isError

                assert "assert 201 == 400" in error_message(result)

    asyncio.run(run())
