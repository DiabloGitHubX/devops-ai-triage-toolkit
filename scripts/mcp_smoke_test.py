"""Exercise the diagnostic server through the real MCP protocol."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from common.mcp_process import build_server_parameters

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def server_parameters(
    overrides: dict[str, str] | None = None,
) -> StdioServerParameters:
    """Configure a separate MCP server subprocess."""

    return build_server_parameters(overrides)


EXPECTED_TOOLS = {
    "list_pods",
    "describe_pod",
    "get_pod_logs",
    "list_events",
    "get_ci_log",
}

TOOL_TIMEOUT = timedelta(seconds=45)


def result_payload(result: Any) -> dict[str, Any]:
    """Extract a structured diagnostic payload."""

    if result.isError:
        raise AssertionError(f"Unexpected MCP tool error: {result.content}")

    if result.structuredContent is not None:
        return result.structuredContent

    for item in result.content:
        if item.type == "text":
            return json.loads(item.text)

    raise AssertionError("No diagnostic payload returned")


async def call_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Invoke an MCP tool and validate its successful response."""

    result = await session.call_tool(
        name,
        arguments=arguments,
        read_timeout_seconds=TOOL_TIMEOUT,
    )

    payload = result_payload(result)

    print(f"[PASS] MCP tools/call: {name}")

    return payload


async def expect_error(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    expected_message: str | None = None,
) -> None:
    """Verify that an unsafe or invalid request is rejected."""

    result = await session.call_tool(
        name,
        arguments=arguments,
        read_timeout_seconds=TOOL_TIMEOUT,
    )

    assert result.isError, f"Expected MCP error for {name}"

    message = "\n".join(item.text for item in result.content if item.type == "text")

    if expected_message:
        assert expected_message.lower() in message.lower(), (
            f"Unexpected error message: {message}"
        )

    assert "Traceback (most recent call last)" not in message

    print(f"[PASS] Rejected {name}: {message}")


async def test_live_server() -> None:
    """Verify discovery and all five tools through MCP."""

    parameters = server_parameters()

    async with (
        stdio_client(parameters) as (
            read_stream,
            write_stream,
        ),
        ClientSession(
            read_stream,
            write_stream,
        ) as session,
    ):
        print("===== MCP PROTOCOL INITIALIZATION =====")

        initialized = await session.initialize()

        assert initialized.serverInfo.name == "devops-ai-triage-toolkit"

        print("[PASS] MCP initialization")
        print(f"  Server: {initialized.serverInfo.name}")
        print(f"  Protocol: {initialized.protocolVersion}")

        print("\n===== MCP TOOL DISCOVERY =====")

        discovered = await session.list_tools()

        names = {tool.name for tool in discovered.tools}

        assert names == EXPECTED_TOOLS
        assert len(discovered.tools) == 5

        for tool in discovered.tools:
            assert tool.description
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False

            print(f"[PASS] Discovered: {tool.name}")
            print("  Input schema: " + json.dumps(tool.inputSchema))

        print("\n===== LIVE KUBERNETES TOOLS =====")

        pods = await call_tool(
            session,
            "list_pods",
            {"namespace": "staging"},
        )

        assert pods["count"] == 3

        pod_names = {}

        for workload in [
            "payments-api",
            "orders-api",
            "analytics-worker",
        ]:
            matches = [
                pod["name"]
                for pod in pods["pods"]
                if pod["name"].startswith(f"{workload}-")
            ]

            assert len(matches) == 1
            pod_names[workload] = matches[0]

        for workload, pod_name in pod_names.items():
            description = await call_tool(
                session,
                "describe_pod",
                {
                    "namespace": "staging",
                    "pod_name": pod_name,
                },
            )

            assert description["name"] == pod_name

            print(
                f"  {workload}: "
                f"phase={description['phase']}, "
                f"ready={description['ready']}"
            )

        print("\n===== CONTAINER LOG EVIDENCE =====")

        arguments = {
            "namespace": "staging",
            "pod_name": pod_names["orders-api"],
            "container": "orders-api",
            "tail_lines": 100,
        }

        result = await session.call_tool(
            "get_pod_logs",
            arguments=arguments,
            read_timeout_seconds=TOOL_TIMEOUT,
        )

        if result.isError:
            print("[INFO] Current logs unavailable; trying previous logs")

            arguments["previous"] = True

            result = await session.call_tool(
                "get_pod_logs",
                arguments=arguments,
                read_timeout_seconds=TOOL_TIMEOUT,
            )

        logs = result_payload(result)

        assert "DATABASE_URL" in logs["logs"]

        print("[PASS] MCP tools/call: get_pod_logs")
        print(logs["logs"])

        print("\n===== KUBERNETES EVENTS =====")

        events = await call_tool(
            session,
            "list_events",
            {"namespace": "staging"},
        )

        print(f"  Returned events: {events['count']}")

        analytics_events = await call_tool(
            session,
            "list_events",
            {
                "namespace": "staging",
                "involved_object": pod_names["analytics-worker"],
            },
        )

        assert analytics_events["events"]

        assert any(
            event["reason"] == "FailedScheduling"
            and "Insufficient cpu" in event["message"]
            for event in analytics_events["events"]
        )

        print("[PASS] Scheduling failure evidence found")

        print("\n===== CI DIAGNOSTIC TOOL =====")

        expected_evidence = {
            "build-1423": "assert 201 == 400",
            "build-1424": "/requirements.txt",
            "build-1425": "nil pointer",
        }

        for job_id, evidence in expected_evidence.items():
            ci_log = await call_tool(
                session,
                "get_ci_log",
                {
                    "job_id": job_id,
                    "failing_section_only": True,
                },
            )

            assert evidence in ci_log["logs"]

            print(
                f"  {job_id}: {ci_log['selected_lines']}/{ci_log['total_lines']} lines"
            )

        print("\n===== MCP SECURITY VALIDATION =====")

        await expect_error(
            session,
            "list_pods",
            {"namespace": "kube-system"},
            "allowlist",
        )

        await expect_error(
            session,
            "describe_pod",
            {
                "namespace": "default",
                "pod_name": pod_names["orders-api"],
            },
            "allowlist",
        )

        await expect_error(
            session,
            "get_pod_logs",
            {
                "namespace": "kube-system",
                "pod_name": pod_names["orders-api"],
            },
            "allowlist",
        )

        await expect_error(
            session,
            "list_events",
            {"namespace": "default"},
            "allowlist",
        )

        await expect_error(
            session,
            "get_pod_logs",
            {
                "namespace": "staging",
                "pod_name": pod_names["orders-api"],
                "tail_lines": 501,
            },
            "500",
        )

        await expect_error(
            session,
            "get_ci_log",
            {"job_id": "../../.env"},
            "Invalid CI job identifier",
        )

        await expect_error(
            session,
            "describe_pod",
            {
                "namespace": "staging",
                "pod_name": "nonexistent-pod-12345",
            },
            "not found",
        )

        await expect_error(
            session,
            "list_pods",
            {},
        )

        print("[PASS] Required argument validation")

    print("[PASS] Live MCP session closed")


async def test_ci_without_kubeconfig() -> None:
    """Verify CI diagnostics remain available without Kubernetes."""

    print("\n===== CI WITHOUT KUBERNETES CREDENTIALS =====")

    missing_path = PROJECT_ROOT / ".runtime" / "nonexistent-smoke-test-kubeconfig"

    assert not missing_path.exists()

    parameters = server_parameters(
        {
            "KUBECONFIG_PATH": str(missing_path),
        }
    )

    async with (
        stdio_client(parameters) as (
            read_stream,
            write_stream,
        ),
        ClientSession(
            read_stream,
            write_stream,
        ) as session,
    ):
        await session.initialize()

        result = await call_tool(
            session,
            "get_ci_log",
            {
                "job_id": "build-1423",
                "failing_section_only": True,
            },
        )

        assert "assert 201 == 400" in result["logs"]

        print("[PASS] CI works without kubeconfig")

        await expect_error(
            session,
            "list_pods",
            {"namespace": "staging"},
            "kubeconfig is missing",
        )

        result = await call_tool(
            session,
            "get_ci_log",
            {"job_id": "build-1424"},
        )

        assert "/requirements.txt" in result["logs"]

        print("[PASS] CI remains available after Kubernetes initialization failure")

    print("[PASS] Independent CI MCP session closed")


async def main() -> None:
    """Run the complete MCP protocol smoke test."""

    await test_live_server()
    await test_ci_without_kubeconfig()

    print("\n===== ALL MCP INTEGRATION TESTS PASSED =====")


if __name__ == "__main__":
    asyncio.run(main())
