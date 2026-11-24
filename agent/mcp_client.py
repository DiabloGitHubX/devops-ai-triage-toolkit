"""Read-only MCP client for the diagnostic agent."""

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from common.mcp_process import build_server_parameters

EXPECTED_SERVER_NAME = "devops-ai-triage-toolkit"

ALLOWED_TOOLS = frozenset(
    {
        "list_pods",
        "describe_pod",
        "get_pod_logs",
        "list_events",
        "get_ci_log",
    }
)

MAX_ARGUMENT_BYTES = 8 * 1024
MAX_TOOL_RESULT_BYTES = 64 * 1024


class MCPClientError(RuntimeError):
    """A controlled MCP client initialization error."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Normalized result of an MCP tool invocation."""

    success: bool
    payload: dict[str, Any]

    def to_json(self) -> str:
        """Serialize the result for the LLM conversation."""

        return json.dumps(
            {
                "success": self.success,
                "payload": self.payload,
            },
            ensure_ascii=True,
            allow_nan=False,
        )


def error_result(message: str) -> ToolResult:
    """Create a controlled tool failure result."""

    return ToolResult(
        success=False,
        payload={"error": message},
    )


class DiagnosticMCPClient:
    """Discover and invoke approved tools through MCP."""

    def __init__(
        self,
        session: ClientSession,
        timeout_seconds: int = 45,
    ) -> None:
        self._session = session
        self._timeout = timedelta(seconds=timeout_seconds)

        self._tools: dict[str, dict[str, Any]] = {}
        self._validators: dict[str, Draft202012Validator] = {}

    @property
    def tool_names(self) -> frozenset[str]:
        """Return the currently discovered tool names."""

        return frozenset(self._tools)

    async def discover_tools(self) -> None:
        """Discover and validate the expected diagnostic tools."""

        discovered = await self._session.list_tools()

        names = [tool.name for tool in discovered.tools]

        if (
            set(names) != ALLOWED_TOOLS
            or len(names) != len(ALLOWED_TOOLS)
            or discovered.nextCursor is not None
        ):
            raise MCPClientError("Unexpected MCP tool inventory.")

        tools = {}
        validators = {}

        for tool in discovered.tools:
            annotations = tool.annotations

            if (
                annotations is None
                or annotations.readOnlyHint is not True
                or annotations.destructiveHint is not False
            ):
                raise MCPClientError("MCP tool safety annotations are invalid.")

            if not tool.description or not tool.description.strip():
                raise MCPClientError("MCP tool description is missing.")

            schema = deepcopy(tool.inputSchema)

            if schema.get("type") != "object":
                raise MCPClientError("MCP tool input schema must describe an object.")

            # Reject unexpected arguments at the client boundary.
            schema["additionalProperties"] = False

            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError:
                raise MCPClientError("MCP tool input schema is invalid.") from None

            validators[tool.name] = Draft202012Validator(schema)

            tools[tool.name] = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                },
            }

        self._tools = tools
        self._validators = validators

    def llm_tools(self) -> list[dict[str, Any]]:
        """Return independent OpenAI-compatible tool definitions."""

        return deepcopy([self._tools[name] for name in sorted(self._tools)])

    def validate_arguments(
        self,
        name: str,
        arguments: Any,
    ) -> str | None:
        """Return a sanitized validation error, if applicable."""

        if name not in ALLOWED_TOOLS:
            return "Tool is not permitted."

        if name not in self._validators:
            return "Tool has not been discovered."

        if not isinstance(arguments, dict):
            return "Tool arguments must be a JSON object."

        try:
            serialized = json.dumps(
                arguments,
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError, RecursionError):
            return "Tool arguments are not valid JSON."

        if len(serialized.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            return "Tool arguments exceed the supported size limit."

        if not self._validators[name].is_valid(arguments):
            return "Tool arguments do not match the MCP input schema."

        return None

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Validate and execute a read-only MCP tool."""

        validation_error = self.validate_arguments(
            name,
            arguments,
        )

        if validation_error:
            return error_result(validation_error)

        try:
            result = await self._session.call_tool(
                name,
                arguments=arguments,
                read_timeout_seconds=self._timeout,
            )

        except Exception:  # noqa: BLE001
            return error_result("MCP tool request failed or timed out.")

        if result.isError:
            messages = [item.text for item in result.content if item.type == "text"]

            payload = {"error": ("\n".join(messages) or "MCP tool returned an error.")}

            return self._bound_result(
                ToolResult(
                    success=False,
                    payload=payload,
                )
            )

        payload = result.structuredContent

        if payload is None:
            for item in result.content:
                if item.type != "text":
                    continue

                if len(item.text.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
                    return error_result(
                        "MCP response exceeds the supported size limit."
                    )

                try:
                    payload = json.loads(item.text)
                except (ValueError, RecursionError):
                    return error_result("MCP tool returned invalid JSON.")

                break

        if not isinstance(payload, dict):
            return error_result("MCP tool returned no structured diagnostic payload.")

        return self._bound_result(
            ToolResult(
                success=True,
                payload=payload,
            )
        )

    @staticmethod
    def _bound_result(result: ToolResult) -> ToolResult:
        """Enforce the maximum serialized diagnostic result size."""

        try:
            serialized = result.to_json().encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            return error_result("MCP tool returned an invalid diagnostic payload.")

        if len(serialized) > MAX_TOOL_RESULT_BYTES:
            return error_result("MCP response exceeds the supported size limit.")

        return result


@asynccontextmanager
async def connect_mcp(
    timeout_seconds: int = 45,
    overrides: Mapping[str, str] | None = None,
) -> AsyncIterator[DiagnosticMCPClient]:
    """Open a managed MCP stdio session."""

    parameters = build_server_parameters(overrides)

    async with (
        stdio_client(parameters) as (
            read_stream,
            write_stream,
        ),
        ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=timeout_seconds),
        ) as session,
    ):
        initialized = await session.initialize()

        if initialized.serverInfo.name != EXPECTED_SERVER_NAME:
            raise MCPClientError("Unexpected MCP server identity.")

        client = DiagnosticMCPClient(
            session=session,
            timeout_seconds=timeout_seconds,
        )

        await client.discover_tools()

        yield client
