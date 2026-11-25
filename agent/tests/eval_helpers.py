"""Deterministic synthetic data for evaluation regression tests."""

import json
from typing import Any

INVESTIGATION_ID = "synthetic-evaluation-test"

LIMITS = {
    "max_steps": 10,
    "max_llm_calls": 12,
    "max_runtime": 300,
    "token_budget": 30000,
}

DIAGNOSIS = """### Symptom
CI job build-1423 failed during unit testing.

### Evidence
- test_negative_amount_rejected
- E   assert 201 == 400

### Root cause
The application accepts negative payment amounts because
negative amount validation is missing.

### Suggested fix
Reject negative payment amounts before processing the request.
Return HTTP 400 and rerun the failing unit test.

### Confidence
High.
"""


def make_case() -> dict[str, Any]:
    """Return an independent synthetic evaluation case."""

    return {
        "id": "ci-test-failure",
        "category": "ci",
        "description": "Synthetic negative payment failure.",
        "arguments": ["--ci", "build-1423"],
        "expected_root_cause": ("Negative payment amounts are incorrectly accepted."),
        "root_cause_groups": [
            ["negative"],
            ["payment", "amounts"],
            ["accepts", "validation"],
        ],
        "evidence_groups": [
            ["test_negative_amount_rejected"],
            ["201 == 400"],
        ],
        "required_successful_tools": [
            "get_ci_log",
        ],
    }


def make_event(
    event: str,
    **fields: Any,
) -> dict[str, Any]:
    """Construct one synthetic agent trace event."""

    return {
        "component": "agent",
        "investigation_id": INVESTIGATION_ID,
        "event": event,
        **fields,
    }


def make_trace_events() -> list[dict[str, Any]]:
    """Construct a complete successful investigation trace."""

    return [
        make_event(
            "investigation_started",
            **LIMITS,
        ),
        make_event(
            "llm_request_started",
            llm_call=1,
        ),
        make_event(
            "llm_request_completed",
            llm_call=1,
            prompt_tokens=1000,
            completion_tokens=100,
            total_tokens=1100,
        ),
        make_event(
            "tool_call_started",
            step=1,
            tool="get_ci_log",
            purpose="Retrieve CI failure evidence.",
        ),
        make_event(
            "tool_call_completed",
            step=1,
            tool="get_ci_log",
            status="success",
            duration_seconds=0.1,
        ),
        make_event(
            "llm_request_started",
            llm_call=2,
        ),
        make_event(
            "llm_request_completed",
            llm_call=2,
            prompt_tokens=2000,
            completion_tokens=400,
            total_tokens=2400,
        ),
        make_event(
            "investigation_finished",
            completed=True,
            stop_reason="diagnosis_completed",
            llm_call=2,
            tool_attempts=1,
            successful_tools=1,
            failed_tools=0,
            prompt_tokens=3000,
            completion_tokens=500,
            total_tokens=3500,
            token_budget=30000,
            usage_complete=True,
            duration_seconds=2.5,
        ),
    ]


def serialize_trace(
    events: list[dict[str, Any]],
) -> str:
    """Serialize trace events as JSON Lines."""

    return (
        "\n".join(
            json.dumps(
                event,
                ensure_ascii=False,
                allow_nan=False,
            )
            for event in events
        )
        + "\n"
    )


def make_trace() -> str:
    """Return a fresh successful synthetic trace."""

    return serialize_trace(make_trace_events())
