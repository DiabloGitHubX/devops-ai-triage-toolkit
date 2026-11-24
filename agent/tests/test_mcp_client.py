"""Regression tests for the agent-side MCP client."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
    ToolAnnotations,
)

from agent import mcp_client
from agent.mcp_client import (
    ALLOWED_TOOLS,
    EXPECTED_SERVER_NAME,
    MAX_ARGUMENT_BYTES,
    MAX_TOOL_RESULT_BYTES,
    DiagnosticMCPClient,
    MCPClientError,
    ToolResult,
    connect_mcp,
    error_result,
)


def make_tool(name):
    """Construct a synthetic MCP tool using SDK data models."""

    if name == "get_ci_log":
        schema = {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "failing_section_only": {"type": "boolean"},
            },
            "required": ["job_id"],
        }

    elif name == "get_pod_logs":
        schema = {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "pod_name": {"type": "string"},
                "tail_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                },
                "previous": {"type": "boolean"},
            },
            "required": ["namespace", "pod_name"],
        }

    else:
        schema = {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
            "required": ["namespace"],
        }

    return Tool(
        name=name,
        description=f"Retrieve diagnostic evidence using {name}.",
        inputSchema=schema,
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )


@pytest.fixture
def inventory():
    """Provide exactly the approved diagnostic tools."""

    return [make_tool(name) for name in sorted(ALLOWED_TOOLS)]


@pytest.fixture
def session(inventory):
    """Provide a mocked asynchronous MCP session."""

    client = MagicMock()

    client.list_tools = AsyncMock(return_value=ListToolsResult(tools=inventory))

    client.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[],
            structuredContent={
                "job_id": "build-1423",
                "logs": "assert 201 == 400",
            },
        )
    )

    client.initialize = AsyncMock(
        return_value=SimpleNamespace(
            serverInfo=SimpleNamespace(
                name=EXPECTED_SERVER_NAME,
            )
        )
    )

    return client


@pytest.fixture
def client(session):
    """Provide an initialized diagnostic MCP client."""

    diagnostic_client = DiagnosticMCPClient(session)

    asyncio.run(diagnostic_client.discover_tools())

    return diagnostic_client


def test_tool_result_serialization():
    result = ToolResult(
        success=True,
        payload={"logs": "diagnostic evidence"},
    )

    assert json.loads(result.to_json()) == {
        "success": True,
        "payload": {"logs": "diagnostic evidence"},
    }


def test_error_result():
    result = error_result("Controlled failure.")

    assert result.success is False
    assert result.payload == {
        "error": "Controlled failure.",
    }


def test_tool_discovery(client, session):
    assert client.tool_names == ALLOWED_TOOLS
    assert len(client.tool_names) == 5

    session.list_tools.assert_awaited_once()


def test_empty_client_before_discovery(session):
    diagnostic_client = DiagnosticMCPClient(session)

    assert diagnostic_client.tool_names == frozenset()
    assert diagnostic_client.llm_tools() == []


@pytest.mark.parametrize(
    "inventory_problem",
    [
        "missing",
        "additional",
        "duplicate",
        "empty",
        "paginated",
    ],
)
def test_reject_unexpected_tool_inventory(
    session,
    inventory,
    inventory_problem,
):
    tools = list(inventory)
    cursor = None

    if inventory_problem == "missing":
        tools.pop()

    elif inventory_problem == "additional":
        tools.append(make_tool("delete_pod"))

    elif inventory_problem == "duplicate":
        tools.append(tools[0])

    elif inventory_problem == "empty":
        tools = []

    elif inventory_problem == "paginated":
        cursor = "next-page"

    session.list_tools.return_value = ListToolsResult(
        tools=tools,
        nextCursor=cursor,
    )

    diagnostic_client = DiagnosticMCPClient(session)

    with pytest.raises(
        MCPClientError,
        match="Unexpected MCP tool inventory",
    ):
        asyncio.run(diagnostic_client.discover_tools())

    assert diagnostic_client.tool_names == frozenset()


@pytest.mark.parametrize(
    "annotations",
    [
        None,
        ToolAnnotations(),
        ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
        ),
        ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=True,
        ),
        ToolAnnotations(
            readOnlyHint=True,
        ),
        ToolAnnotations(
            destructiveHint=False,
        ),
    ],
)
def test_reject_unsafe_tool_annotations(
    session,
    inventory,
    annotations,
):
    inventory[0].annotations = annotations

    diagnostic_client = DiagnosticMCPClient(session)

    with pytest.raises(
        MCPClientError,
        match="safety annotations are invalid",
    ):
        asyncio.run(diagnostic_client.discover_tools())

    assert diagnostic_client.tool_names == frozenset()


@pytest.mark.parametrize(
    "description",
    [None, "", "   "],
)
def test_reject_missing_tool_description(
    session,
    inventory,
    description,
):
    inventory[0].description = description

    diagnostic_client = DiagnosticMCPClient(session)

    with pytest.raises(
        MCPClientError,
        match="description is missing",
    ):
        asyncio.run(diagnostic_client.discover_tools())


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "string"},
        {"type": "array"},
        {"type": "integer"},
    ],
)
def test_reject_non_object_schema(
    session,
    inventory,
    schema,
):
    inventory[0].inputSchema = schema

    diagnostic_client = DiagnosticMCPClient(session)

    with pytest.raises(
        MCPClientError,
        match="must describe an object",
    ):
        asyncio.run(diagnostic_client.discover_tools())


@pytest.mark.parametrize(
    "schema",
    [
        {
            "type": "object",
            "properties": "invalid",
        },
        {
            "type": "object",
            "required": "namespace",
        },
        {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "invalid-type",
                }
            },
        },
    ],
)
def test_reject_invalid_json_schema(
    session,
    inventory,
    schema,
):
    inventory[0].inputSchema = schema

    diagnostic_client = DiagnosticMCPClient(session)

    with pytest.raises(
        MCPClientError,
        match="input schema is invalid",
    ):
        asyncio.run(diagnostic_client.discover_tools())


def test_llm_tool_definitions(client):
    definitions = client.llm_tools()

    names = [definition["function"]["name"] for definition in definitions]

    assert names == sorted(ALLOWED_TOOLS)

    for definition in definitions:
        assert definition["type"] == "function"

        function = definition["function"]

        assert function["description"]
        assert function["parameters"]["type"] == "object"

        assert function["parameters"]["additionalProperties"] is False


def test_llm_schema_isolation(client):
    definitions = client.llm_tools()

    definition = next(
        item for item in definitions if item["function"]["name"] == "get_ci_log"
    )

    definition["function"]["parameters"]["required"].clear()

    definition["function"]["parameters"]["additionalProperties"] = True

    fresh_definition = next(
        item for item in client.llm_tools() if item["function"]["name"] == "get_ci_log"
    )

    assert fresh_definition["function"]["parameters"]["required"] == ["job_id"]

    assert fresh_definition["function"]["parameters"]["additionalProperties"] is False

    assert client.validate_arguments("get_ci_log", {}) is not None


def test_discovery_does_not_modify_server_schema(
    client,
    inventory,
):
    for tool in inventory:
        assert "additionalProperties" not in tool.inputSchema

    assert len(client.llm_tools()) == 5


@pytest.mark.parametrize(
    "name",
    [
        "delete_pod",
        "apply_manifest",
        "exec_command",
        "get_secret",
        "unknown_tool",
        "",
    ],
)
def test_reject_unauthorized_tool(client, name):
    assert client.validate_arguments(name, {}) == "Tool is not permitted."


def test_reject_undiscovered_tool(session):
    diagnostic_client = DiagnosticMCPClient(session)

    assert (
        diagnostic_client.validate_arguments(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
        == "Tool has not been discovered."
    )


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        [],
        "invalid",
        123,
        True,
    ],
)
def test_reject_non_object_arguments(client, arguments):
    assert (
        client.validate_arguments(
            "get_ci_log",
            arguments,
        )
        == "Tool arguments must be a JSON object."
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"job_id": 1423},
        {"job_id": None},
        {"job_id": ["build-1423"]},
        {
            "job_id": "build-1423",
            "failing_section_only": "true",
        },
        {
            "job_id": "build-1423",
            "unexpected_argument": True,
        },
    ],
)
def test_reject_invalid_schema_arguments(client, arguments):
    assert (
        client.validate_arguments(
            "get_ci_log",
            arguments,
        )
        == "Tool arguments do not match the MCP input schema."
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"job_id": "build-1423"},
        {
            "job_id": "build-1423",
            "failing_section_only": True,
        },
        {
            "job_id": "build-1423",
            "failing_section_only": False,
        },
    ],
)
def test_accept_valid_ci_arguments(client, arguments):
    assert (
        client.validate_arguments(
            "get_ci_log",
            arguments,
        )
        is None
    )


@pytest.mark.parametrize(
    "tail_lines",
    [1, 100, 500],
)
def test_accept_valid_log_tail(client, tail_lines):
    assert (
        client.validate_arguments(
            "get_pod_logs",
            {
                "namespace": "staging",
                "pod_name": "orders-api",
                "tail_lines": tail_lines,
            },
        )
        is None
    )


@pytest.mark.parametrize(
    "tail_lines",
    [0, -1, 501, "100", True, None, 1.5],
)
def test_reject_invalid_log_tail(client, tail_lines):
    assert (
        client.validate_arguments(
            "get_pod_logs",
            {
                "namespace": "staging",
                "pod_name": "orders-api",
                "tail_lines": tail_lines,
            },
        )
        is not None
    )


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        object(),
        {"unsupported-set"},
    ],
)
def test_reject_non_json_values(client, value):
    assert (
        client.validate_arguments(
            "get_ci_log",
            {"job_id": value},
        )
        == "Tool arguments are not valid JSON."
    )


def test_reject_circular_arguments(client):
    arguments = {"job_id": "build-1423"}
    arguments["recursive"] = arguments

    assert (
        client.validate_arguments(
            "get_ci_log",
            arguments,
        )
        == "Tool arguments are not valid JSON."
    )


def test_reject_oversized_arguments(client):
    arguments = {
        "job_id": "x" * MAX_ARGUMENT_BYTES,
    }

    assert (
        client.validate_arguments(
            "get_ci_log",
            arguments,
        )
        == "Tool arguments exceed the supported size limit."
    )


def test_argument_size_boundary(client):
    overhead = len(
        json.dumps(
            {"job_id": ""},
            ensure_ascii=True,
        ).encode("utf-8")
    )

    allowed = {
        "job_id": "x" * (MAX_ARGUMENT_BYTES - overhead),
    }

    rejected = {
        "job_id": "x" * (MAX_ARGUMENT_BYTES - overhead + 1),
    }

    assert (
        client.validate_arguments(
            "get_ci_log",
            allowed,
        )
        is None
    )

    assert (
        client.validate_arguments(
            "get_ci_log",
            rejected,
        )
        is not None
    )


def test_successful_tool_call(client, session):
    arguments = {
        "job_id": "build-1423",
        "failing_section_only": True,
    }

    result = asyncio.run(client.call_tool("get_ci_log", arguments))

    assert result.success is True
    assert result.payload["job_id"] == "build-1423"
    assert "assert 201 == 400" in result.payload["logs"]

    session.call_tool.assert_awaited_once_with(
        "get_ci_log",
        arguments=arguments,
        read_timeout_seconds=timedelta(seconds=45),
    )


def test_custom_request_timeout(session):
    diagnostic_client = DiagnosticMCPClient(
        session,
        timeout_seconds=15,
    )

    asyncio.run(diagnostic_client.discover_tools())

    arguments = {"job_id": "build-1423"}

    asyncio.run(
        diagnostic_client.call_tool(
            "get_ci_log",
            arguments,
        )
    )

    session.call_tool.assert_awaited_once_with(
        "get_ci_log",
        arguments=arguments,
        read_timeout_seconds=timedelta(seconds=15),
    )


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("delete_pod", {}),
        ("get_ci_log", {}),
        ("get_ci_log", {"job_id": 123}),
        ("get_ci_log", {"job_id": "x" * MAX_ARGUMENT_BYTES}),
    ],
)
def test_invalid_call_never_reaches_server(
    client,
    session,
    name,
    arguments,
):
    result = asyncio.run(client.call_tool(name, arguments))

    assert result.success is False
    assert "error" in result.payload

    session.call_tool.assert_not_awaited()


@pytest.mark.parametrize(
    "exception_type",
    [
        RuntimeError,
        TimeoutError,
        ConnectionError,
        OSError,
    ],
)
def test_transport_errors_are_sanitized(
    client,
    session,
    exception_type,
):
    sensitive_message = "synthetic-private-credential"

    session.call_tool.side_effect = exception_type(sensitive_message)

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False

    assert result.payload == {
        "error": "MCP tool request failed or timed out.",
    }

    assert sensitive_message not in result.to_json()


def test_structured_payload_preferred(client, session):
    session.call_tool.return_value = CallToolResult(
        content=[
            TextContent(
                type="text",
                text="not valid JSON",
            )
        ],
        structuredContent={
            "logs": "structured diagnostic evidence",
        },
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is True
    assert result.payload == {
        "logs": "structured diagnostic evidence",
    }


def test_text_json_fallback(client, session):
    payload = {
        "job_id": "build-1423",
        "logs": "assert 201 == 400",
    }

    session.call_tool.return_value = CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(payload),
            )
        ],
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is True
    assert result.payload == payload


@pytest.mark.parametrize(
    "text",
    [
        "invalid JSON",
        "{",
        "[1, 2, 3]",
        '"plain string"',
        "null",
        "123",
        "true",
    ],
)
def test_reject_invalid_text_payload(
    client,
    session,
    text,
):
    session.call_tool.return_value = CallToolResult(
        content=[
            TextContent(
                type="text",
                text=text,
            )
        ],
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False
    assert "error" in result.payload


def test_reject_empty_response(client, session):
    session.call_tool.return_value = CallToolResult(
        content=[],
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False

    assert result.payload == {
        "error": ("MCP tool returned no structured diagnostic payload."),
    }


def test_server_error_preserved(client, session):
    session.call_tool.return_value = CallToolResult(
        content=[
            TextContent(
                type="text",
                text="Namespace is not allowed.",
            )
        ],
        isError=True,
    )

    result = asyncio.run(
        client.call_tool(
            "list_pods",
            {"namespace": "kube-system"},
        )
    )

    assert result.success is False

    assert result.payload == {
        "error": "Namespace is not allowed.",
    }


def test_server_error_without_text(client, session):
    session.call_tool.return_value = CallToolResult(
        content=[],
        isError=True,
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False

    assert result.payload == {
        "error": "MCP tool returned an error.",
    }


def test_multiple_server_error_messages(client, session):
    session.call_tool.return_value = CallToolResult(
        content=[
            TextContent(
                type="text",
                text="First error.",
            ),
            TextContent(
                type="text",
                text="Second error.",
            ),
        ],
        isError=True,
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False

    assert result.payload["error"] == ("First error.\nSecond error.")


@pytest.mark.parametrize(
    "response_type",
    [
        "structured",
        "text",
        "error",
    ],
)
def test_reject_oversized_response(
    client,
    session,
    response_type,
):
    oversized = "x" * (MAX_TOOL_RESULT_BYTES + 1)

    if response_type == "structured":
        response = CallToolResult(
            content=[],
            structuredContent={"logs": oversized},
        )

    elif response_type == "text":
        response = CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"logs": oversized}),
                )
            ],
        )

    else:
        response = CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=oversized,
                )
            ],
            isError=True,
        )

    session.call_tool.return_value = response

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False

    assert result.payload == {
        "error": "MCP response exceeds the supported size limit.",
    }

    assert len(result.to_json().encode("utf-8")) < 1024


def test_response_size_boundary(client, session):
    overhead = len(
        ToolResult(
            success=True,
            payload={"logs": ""},
        )
        .to_json()
        .encode("utf-8")
    )

    allowed_size = MAX_TOOL_RESULT_BYTES - overhead

    session.call_tool.return_value = CallToolResult(
        content=[],
        structuredContent={
            "logs": "x" * allowed_size,
        },
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is True

    assert len(result.to_json().encode("utf-8")) == (MAX_TOOL_RESULT_BYTES)

    session.call_tool.return_value = CallToolResult(
        content=[],
        structuredContent={
            "logs": "x" * (allowed_size + 1),
        },
    )

    rejected = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert rejected.success is False


def test_response_size_counts_serialized_unicode(
    client,
    session,
):
    session.call_tool.return_value = CallToolResult(
        content=[],
        structuredContent={
            "logs": "\u2603" * MAX_TOOL_RESULT_BYTES,
        },
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False


def test_reject_non_finite_response(client, session):
    session.call_tool.return_value = CallToolResult(
        content=[],
        structuredContent={
            "value": float("nan"),
        },
    )

    result = asyncio.run(
        client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )
    )

    assert result.success is False

    assert result.payload == {
        "error": "MCP tool returned an invalid diagnostic payload.",
    }


def test_session_recovers_after_failed_call(client, session):
    session.call_tool.side_effect = [
        TimeoutError("Synthetic timeout"),
        CallToolResult(
            content=[],
            structuredContent={"logs": "recovered"},
        ),
    ]

    async def exercise():
        first = await client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )

        second = await client.call_tool(
            "get_ci_log",
            {"job_id": "build-1423"},
        )

        return first, second

    first, second = asyncio.run(exercise())

    assert first.success is False
    assert second.success is True
    assert second.payload == {"logs": "recovered"}


@pytest.fixture
def lifecycle(monkeypatch, session):
    """Mock MCP transport and session context managers."""

    events = []
    parameters = object()
    read_stream = object()
    write_stream = object()

    launcher = MagicMock(return_value=parameters)

    @asynccontextmanager
    async def fake_stdio(received_parameters):
        assert received_parameters is parameters

        events.append("transport_enter")

        try:
            yield read_stream, write_stream

        finally:
            events.append("transport_exit")

    @asynccontextmanager
    async def fake_session(
        received_read,
        received_write,
        *,
        read_timeout_seconds,
    ):
        assert received_read is read_stream
        assert received_write is write_stream

        assert read_timeout_seconds == timedelta(
            seconds=15,
        )

        events.append("session_enter")

        try:
            yield session

        finally:
            events.append("session_exit")

    monkeypatch.setattr(
        mcp_client,
        "build_server_parameters",
        launcher,
    )

    monkeypatch.setattr(
        mcp_client,
        "stdio_client",
        fake_stdio,
    )

    monkeypatch.setattr(
        mcp_client,
        "ClientSession",
        fake_session,
    )

    return events, launcher


def test_connection_lifecycle(lifecycle, session):
    events, launcher = lifecycle

    overrides = {
        "ALLOWED_NAMESPACES": "staging",
    }

    async def exercise():
        async with connect_mcp(
            timeout_seconds=15,
            overrides=overrides,
        ) as connected_client:
            events.append("client_ready")

            assert connected_client.tool_names == ALLOWED_TOOLS

    asyncio.run(exercise())

    assert events == [
        "transport_enter",
        "session_enter",
        "client_ready",
        "session_exit",
        "transport_exit",
    ]

    launcher.assert_called_once_with(overrides)

    session.initialize.assert_awaited_once()
    session.list_tools.assert_awaited_once()


def test_unexpected_server_identity_closes_session(
    lifecycle,
    session,
):
    events, _ = lifecycle

    session.initialize.return_value = SimpleNamespace(
        serverInfo=SimpleNamespace(
            name="unexpected-server",
        )
    )

    async def exercise():
        async with connect_mcp(timeout_seconds=15):
            pytest.fail("Unexpected server was accepted.")

    with pytest.raises(
        MCPClientError,
        match="Unexpected MCP server identity",
    ):
        asyncio.run(exercise())

    assert events == [
        "transport_enter",
        "session_enter",
        "session_exit",
        "transport_exit",
    ]

    session.list_tools.assert_not_awaited()


def test_discovery_failure_closes_session(
    lifecycle,
    session,
):
    events, _ = lifecycle

    session.list_tools.return_value = ListToolsResult(
        tools=[],
    )

    async def exercise():
        async with connect_mcp(timeout_seconds=15):
            pytest.fail("Invalid inventory was accepted.")

    with pytest.raises(
        MCPClientError,
        match="Unexpected MCP tool inventory",
    ):
        asyncio.run(exercise())

    assert events == [
        "transport_enter",
        "session_enter",
        "session_exit",
        "transport_exit",
    ]


def test_initialization_failure_closes_session(
    lifecycle,
    session,
):
    events, _ = lifecycle

    session.initialize.side_effect = RuntimeError("Synthetic initialization failure")

    async def exercise():
        async with connect_mcp(timeout_seconds=15):
            pytest.fail("Failed initialization was accepted.")

    with pytest.raises(
        RuntimeError,
        match="Synthetic initialization failure",
    ):
        asyncio.run(exercise())

    assert events == [
        "transport_enter",
        "session_enter",
        "session_exit",
        "transport_exit",
    ]

    session.list_tools.assert_not_awaited()


def test_consumer_failure_closes_session(lifecycle):
    events, _ = lifecycle

    async def exercise():
        async with connect_mcp(timeout_seconds=15):
            events.append("client_ready")

            raise RuntimeError("Synthetic consumer failure")

    with pytest.raises(
        RuntimeError,
        match="Synthetic consumer failure",
    ):
        asyncio.run(exercise())

    assert events == [
        "transport_enter",
        "session_enter",
        "client_ready",
        "session_exit",
        "transport_exit",
    ]
