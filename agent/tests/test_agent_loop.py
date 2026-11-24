"""Regression tests for the bounded autonomous diagnostic agent."""

import json
from dataclasses import replace

import pytest

from agent.agent_loop import (
    estimate_prompt_tokens,
    has_required_headings,
)
from agent.llm_client import (
    LLMClientError,
    TokenUsage,
)
from agent.mcp_client import ToolResult
from agent.tests.helpers import (
    DIAGNOSIS,
    TOOL_SCHEMA,
    final_response,
    requested_call,
    run_agent,
    tool_response,
)


def test_successful_investigation(settings, llm, mcp):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert result.completed
    assert result.stop_reason == "diagnosis_completed"
    assert result.stats.llm_calls == 2
    assert result.stats.tool_attempts == 1
    assert result.stats.successful_tools == 1
    assert result.stats.failed_tools == 0
    assert result.stats.prompt_tokens == 6500
    assert result.stats.completion_tokens == 150
    assert result.stats.total_tokens == 6650
    assert result.stats.usage_complete
    assert len(result.trace) == 1
    assert result.trace[0].success

    mcp.call_tool.assert_awaited_once_with(
        "get_ci_log",
        {
            "job_id": "build-1423",
            "failing_section_only": True,
        },
    )


@pytest.mark.parametrize(
    "query",
    ["", "   ", None, 123, "x" * 4097],
)
def test_invalid_query(settings, llm, mcp, query):
    with pytest.raises(ValueError):
        run_agent(settings, llm, mcp, query)

    llm.complete.assert_not_awaited()
    mcp.call_tool.assert_not_awaited()


@pytest.mark.parametrize(
    "tool_name",
    [
        "delete_pod",
        "exec_command",
        "get_secret",
        "apply_manifest",
    ],
)
def test_unauthorized_tool(settings, llm, mcp, tool_name):
    llm.complete.side_effect = [
        tool_response(requested_call(name=tool_name)),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stats.tool_attempts == 1
    assert result.stats.failed_tools == 1
    assert result.stats.successful_tools == 0
    assert result.stop_reason == "no_successful_diagnostic_calls"

    mcp.call_tool.assert_not_awaited()


@pytest.mark.parametrize(
    "arguments",
    [
        "{invalid-json",
        "",
        '{"job_id":',
        "x" * 8193,
    ],
)
def test_malformed_arguments(settings, llm, mcp, arguments):
    llm.complete.side_effect = [
        tool_response(requested_call(arguments=arguments)),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stats.tool_attempts == 1
    assert result.stats.failed_tools == 1

    mcp.call_tool.assert_not_awaited()


def test_schema_validation_failure(settings, llm, mcp):
    mcp.validate_arguments.return_value = "Invalid tool arguments."

    llm.complete.side_effect = [
        tool_response(requested_call(arguments='{"job_id": 123}')),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stats.failed_tools == 1

    mcp.call_tool.assert_not_awaited()


def test_duplicate_tool_call(settings, llm, mcp):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        tool_response(
            requested_call(
                call_id="call-002",
                arguments=('{"failing_section_only": true, "job_id": "build-1423"}'),
            )
        ),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert result.completed
    assert result.stats.tool_attempts == 2
    assert result.stats.successful_tools == 1
    assert result.stats.failed_tools == 1
    assert len(result.trace) == 2
    assert not result.trace[1].success

    assert mcp.call_tool.await_count == 1


def test_distinct_arguments_are_permitted(settings, llm, mcp):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        tool_response(
            requested_call(
                call_id="call-002",
                arguments=json.dumps(
                    {
                        "job_id": "build-1423",
                        "failing_section_only": False,
                    }
                ),
            )
        ),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert result.completed
    assert result.stats.successful_tools == 2
    assert result.stats.failed_tools == 0
    assert mcp.call_tool.await_count == 2


def test_tool_budget_exhaustion(settings, llm, mcp):
    settings = replace(settings, max_steps=1)

    llm.complete.side_effect = [
        tool_response(
            requested_call(),
            requested_call(
                call_id="call-002",
                arguments='{"job_id": "build-1424"}',
            ),
        ),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert result.completed
    assert result.stats.tool_attempts == 1
    assert result.stats.successful_tools == 1
    assert mcp.call_tool.await_count == 1

    final_request = llm.complete.await_args
    assert final_request.kwargs["tools"] is None


def test_llm_budget_reserves_finalization(settings, llm, mcp):
    settings = replace(settings, max_llm_calls=2)

    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert result.completed
    assert result.stats.llm_calls == 2

    final_request = llm.complete.await_args
    assert final_request.kwargs["tools"] is None


def test_insufficient_estimated_token_budget(
    settings,
    llm,
    mcp,
):
    settings = replace(settings, token_budget=1)

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == ("insufficient_estimated_token_budget")
    assert result.stats.llm_calls == 0

    llm.complete.assert_not_awaited()
    mcp.call_tool.assert_not_awaited()


def test_reported_token_budget_exceeded(settings, llm, mcp):
    response = replace(
        tool_response(requested_call()),
        usage=TokenUsage(
            prompt_tokens=20000,
            completion_tokens=100,
            total_tokens=20100,
        ),
    )

    llm.complete.return_value = response

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == ("reported_token_budget_exceeded")
    assert result.stats.total_tokens == 20100
    assert result.stats.llm_calls == 1

    mcp.call_tool.assert_not_awaited()


def test_missing_token_usage(settings, llm, mcp):
    llm.complete.return_value = replace(
        tool_response(requested_call()),
        usage=None,
    )

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert not result.stats.usage_complete
    assert result.stop_reason == "token_usage_unavailable"

    mcp.call_tool.assert_not_awaited()


def test_llm_provider_failure(settings, llm, mcp):
    llm.complete.side_effect = LLMClientError("Synthetic provider failure.")

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert not result.stats.usage_complete
    assert result.stats.llm_calls == 1
    assert result.stop_reason == "llm_request_failed"

    mcp.call_tool.assert_not_awaited()


def test_llm_timeout(settings, llm, mcp):
    llm.complete.side_effect = TimeoutError

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert not result.stats.usage_complete
    assert result.stop_reason == "llm_request_timeout"

    mcp.call_tool.assert_not_awaited()


def test_mcp_timeout(settings, llm, mcp):
    mcp.call_tool.side_effect = TimeoutError

    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stats.tool_attempts == 1
    assert result.stats.failed_tools == 1
    assert result.stats.successful_tools == 0
    assert result.stop_reason == "no_successful_diagnostic_calls"


def test_mcp_controlled_error(settings, llm, mcp):
    mcp.call_tool.return_value = ToolResult(
        success=False,
        payload={"error": "Namespace access denied."},
    )

    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stats.failed_tools == 1
    assert not result.trace[0].success


def test_runtime_budget_exhausted(settings, llm, mcp):
    settings = replace(settings, max_runtime=0)

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == "runtime_budget_exhausted"

    llm.complete.assert_not_awaited()
    mcp.call_tool.assert_not_awaited()


def test_unexpected_finalization_tool_call(settings, llm, mcp):
    settings = replace(settings, max_steps=1)

    llm.complete.side_effect = [
        tool_response(requested_call()),
        tool_response(
            requested_call(
                call_id="call-002",
                arguments='{"job_id": "build-1424"}',
            )
        ),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == ("unexpected_finalization_tool_calls")
    assert mcp.call_tool.await_count == 1


def test_missing_diagnosis_sections(settings, llm, mcp):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response("Incomplete diagnosis."),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == "invalid_diagnosis_format"


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_final_response(settings, llm, mcp, content):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(content),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == "empty_llm_response"


def test_truncated_llm_response(settings, llm, mcp):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        replace(
            final_response(),
            finish_reason="length",
        ),
    ]

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == "incomplete_llm_response"


def test_diagnosis_without_evidence(settings, llm, mcp):
    llm.complete.return_value = final_response()

    result = run_agent(settings, llm, mcp)

    assert not result.completed
    assert result.stop_reason == "no_successful_diagnostic_calls"
    assert "Unknown" in result.diagnosis

    mcp.call_tool.assert_not_awaited()


def test_required_headings_valid():
    assert has_required_headings(DIAGNOSIS)


def test_required_headings_missing():
    assert not has_required_headings("### Symptom\nCI failed.")


def test_required_headings_wrong_order():
    assert not has_required_headings(
        "### Confidence\n### Suggested fix\n### Root cause\n### Evidence\n### Symptom\n"
    )


def test_token_estimate_positive():
    messages = [{"role": "user", "content": "Investigate CI."}]

    assert estimate_prompt_tokens(messages) > 0


def test_tool_definitions_increase_token_estimate():
    messages = [{"role": "user", "content": "Investigate CI."}]

    assert estimate_prompt_tokens(
        messages,
        [TOOL_SCHEMA],
    ) > estimate_prompt_tokens(messages)


def test_larger_prompt_increases_token_estimate():
    short = [{"role": "user", "content": "short"}]
    long = [{"role": "user", "content": "x" * 10000}]

    assert estimate_prompt_tokens(long) > estimate_prompt_tokens(short)
