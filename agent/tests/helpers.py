"""Shared helpers for isolated agent regression tests."""

import asyncio
import json

from agent.agent_loop import DiagnosticAgent
from agent.llm_client import (
    LLMResponse,
    RequestedToolCall,
    TokenUsage,
)

DIAGNOSIS = """### Symptom
CI unit test failed.

### Evidence
assert 201 == 400

### Root cause
Negative payment amounts are incorrectly accepted.

### Suggested fix
Correct payment amount validation.

### Confidence
High.
"""


QUERY = "Investigate failed CI job build-1423."


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_ci_log",
        "description": "Retrieve CI diagnostic evidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "failing_section_only": {
                    "type": "boolean",
                },
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
}


def requested_call(
    call_id="call-001",
    name="get_ci_log",
    arguments=None,
):
    """Construct a synthetic model tool request."""

    if arguments is None:
        arguments = json.dumps(
            {
                "job_id": "build-1423",
                "failing_section_only": True,
            }
        )

    return RequestedToolCall(
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def tool_response(*calls):
    """Construct an LLM response containing tool requests."""

    return LLMResponse(
        message={
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in calls
            ],
        },
        content=None,
        tool_calls=tuple(calls),
        finish_reason="tool_calls",
        usage=TokenUsage(
            prompt_tokens=3000,
            completion_tokens=50,
            total_tokens=3050,
        ),
    )


def final_response(content=DIAGNOSIS):
    """Construct a synthetic final diagnosis."""

    return LLMResponse(
        message={
            "role": "assistant",
            "content": content,
        },
        content=content,
        tool_calls=(),
        finish_reason="stop",
        usage=TokenUsage(
            prompt_tokens=3500,
            completion_tokens=100,
            total_tokens=3600,
        ),
    )


def run_agent(settings, llm, mcp, query=QUERY):
    """Execute an investigation without external services."""

    agent = DiagnosticAgent(
        settings=settings,
        skill="Use diagnostic evidence. Never execute remediation.",
        llm=llm,
        mcp=mcp,
    )

    return asyncio.run(agent.investigate(query))
