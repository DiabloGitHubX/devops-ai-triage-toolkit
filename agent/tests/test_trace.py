"""Regression tests for structured agent execution tracing."""

import asyncio
import io
import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from agent.llm_client import LLMClientError
from agent.mcp_client import ToolResult
from agent.tests.helpers import (
    final_response,
    requested_call,
    run_agent,
    tool_response,
)
from agent.trace import (
    LOGGER_NAME,
    InvestigationTracer,
    JSONTraceFormatter,
    configure_trace_logging,
)


@pytest.fixture
def trace_stream(monkeypatch):
    """Capture structured trace events without external services."""

    stream = io.StringIO()

    logger = logging.Logger(LOGGER_NAME)  # noqa: LOG001
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONTraceFormatter())
    logger.addHandler(handler)

    original_get_logger = logging.getLogger

    def get_logger(name=None):
        if name == LOGGER_NAME:
            return logger

        return original_get_logger(name)

    monkeypatch.setattr(logging, "getLogger", get_logger)

    yield stream

    logger.removeHandler(handler)
    handler.close()


def read_events(stream):
    """Deserialize captured JSON lines."""

    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def find_events(events, event_name):
    """Return events matching the requested event type."""

    return [event for event in events if event["event"] == event_name]


def test_valid_json_event(trace_stream):
    tracer = InvestigationTracer()

    tracer.emit(
        "investigation_started",
        max_steps=10,
        token_budget=20000,
    )

    events = read_events(trace_stream)

    assert len(events) == 1

    event = events[0]

    assert event["event"] == "investigation_started"
    assert event["component"] == "agent"
    assert event["level"] == "INFO"
    assert event["max_steps"] == 10
    assert event["token_budget"] == 20000

    assert UUID(event["investigation_id"]).version == 4


def test_timestamp_is_utc(trace_stream):
    tracer = InvestigationTracer()
    tracer.emit("investigation_started")

    event = read_events(trace_stream)[0]

    timestamp = datetime.fromisoformat(event["timestamp"])

    assert timestamp.utcoffset() == timedelta(0)


def test_investigation_ids_are_unique(trace_stream):
    first = InvestigationTracer()
    second = InvestigationTracer()

    first.emit("investigation_started")
    second.emit("investigation_started")

    events = read_events(trace_stream)

    assert len(events) == 2

    assert events[0]["investigation_id"] != events[1]["investigation_id"]


def test_event_correlation(trace_stream):
    tracer = InvestigationTracer()

    tracer.emit("investigation_started")
    tracer.emit(
        "tool_call_started",
        step=1,
        tool="get_ci_log",
    )
    tracer.emit(
        "investigation_finished",
        completed=True,
    )

    events = read_events(trace_stream)

    assert len(events) == 3

    assert {event["investigation_id"] for event in events} == {tracer.investigation_id}


@pytest.mark.parametrize(
    "event_name",
    [
        "unknown_event",
        "",
        "execute_remediation",
    ],
)
def test_unsupported_events_rejected(
    trace_stream,
    event_name,
):
    tracer = InvestigationTracer()

    with pytest.raises(
        ValueError,
        match="Unsupported trace event",
    ):
        tracer.emit(event_name)

    assert read_events(trace_stream) == []


@pytest.mark.parametrize(
    "field_name",
    [
        "api_key",
        "password",
        "token",
        "credentials",
        "kubeconfig",
        "prompt",
        "arguments",
        "raw_result",
        "query",
        "diagnosis",
        "reasoning",
        "exception",
    ],
)
def test_sensitive_metadata_fields_rejected(
    trace_stream,
    field_name,
):
    tracer = InvestigationTracer()

    with pytest.raises(
        ValueError,
        match="Unsupported trace metadata field",
    ):
        tracer.emit(
            "investigation_started",
            **{field_name: "synthetic-sensitive-value"},
        )

    assert read_events(trace_stream) == []

    assert "synthetic-sensitive-value" not in trace_stream.getvalue()


@pytest.mark.parametrize(
    "value",
    [
        {"secret": "synthetic-secret"},
        ["synthetic-secret"],
        ("synthetic-secret",),
        object(),
    ],
)
def test_non_scalar_metadata_rejected(
    trace_stream,
    value,
):
    tracer = InvestigationTracer()

    with pytest.raises(
        ValueError,
        match="Trace metadata must contain scalar values",
    ):
        tracer.emit(
            "tool_call_started",
            purpose=value,
        )

    assert read_events(trace_stream) == []


def test_scalar_metadata_supported(trace_stream):
    tracer = InvestigationTracer()

    tracer.emit(
        "investigation_finished",
        completed=True,
        total_tokens=6650,
        duration_seconds=0.125,
        stop_reason="diagnosis_completed",
        status=None,
    )

    event = read_events(trace_stream)[0]

    assert event["completed"] is True
    assert event["total_tokens"] == 6650
    assert event["duration_seconds"] == 0.125
    assert event["status"] is None


def test_unstructured_message_is_not_exposed(
    trace_stream,
):
    logger = logging.getLogger(LOGGER_NAME)

    logger.info("synthetic-sensitive-message")

    events = read_events(trace_stream)

    assert len(events) == 1
    assert events[0]["event"] == "unstructured_log"

    assert "synthetic-sensitive-message" not in trace_stream.getvalue()


def test_logger_configuration_is_idempotent(
    trace_stream,
    capsys,
):
    first = configure_trace_logging()
    second = configure_trace_logging()

    assert first is second
    assert second.propagate is False
    assert second.level == logging.INFO
    assert len(second.handlers) == 1

    tracer = InvestigationTracer(second)
    tracer.emit("investigation_started")

    captured = capsys.readouterr()

    assert captured.out == ""

    events = [json.loads(line) for line in captured.err.splitlines()]

    assert len(events) == 1
    assert events[0]["event"] == "investigation_started"


def test_successful_investigation_event_sequence(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    assert result.completed

    assert [event["event"] for event in events] == [
        "investigation_started",
        "llm_request_started",
        "llm_request_completed",
        "tool_call_started",
        "tool_call_completed",
        "llm_request_started",
        "llm_request_completed",
        "investigation_finished",
    ]

    assert len({event["investigation_id"] for event in events}) == 1

    timestamps = [datetime.fromisoformat(event["timestamp"]) for event in events]

    assert timestamps == sorted(timestamps)


def test_successful_tool_execution_metadata(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    started = find_events(
        events,
        "tool_call_started",
    )[0]

    completed = find_events(
        events,
        "tool_call_completed",
    )[0]

    assert started["step"] == 1
    assert completed["step"] == 1

    assert started["tool"] == "get_ci_log"
    assert completed["tool"] == "get_ci_log"

    assert started["purpose"]
    assert started["purpose"] == completed["purpose"]

    assert completed["status"] == "success"
    assert completed["duration_seconds"] >= 0

    assert completed["duration_seconds"] == result.trace[0].duration_seconds


def test_llm_token_accounting(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    requests = find_events(
        events,
        "llm_request_completed",
    )

    assert len(requests) == 2

    assert requests[0]["llm_call"] == 1
    assert requests[0]["prompt_tokens"] == 3000
    assert requests[0]["completion_tokens"] == 50
    assert requests[0]["total_tokens"] == 3050
    assert requests[0]["tool_count"] == 1

    assert requests[1]["llm_call"] == 2
    assert requests[1]["prompt_tokens"] == 3500
    assert requests[1]["completion_tokens"] == 100
    assert requests[1]["total_tokens"] == 6650
    assert requests[1]["tool_count"] == 0

    assert requests[1]["total_tokens"] == result.stats.total_tokens


def test_final_statistics_match_result(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    event = read_events(trace_stream)[-1]

    assert event["event"] == "investigation_finished"
    assert event["completed"] == result.completed
    assert event["stop_reason"] == result.stop_reason

    assert event["llm_call"] == result.stats.llm_calls

    assert event["tool_attempts"] == result.stats.tool_attempts

    assert event["successful_tools"] == result.stats.successful_tools

    assert event["failed_tools"] == result.stats.failed_tools

    assert event["prompt_tokens"] == result.stats.prompt_tokens

    assert event["completion_tokens"] == result.stats.completion_tokens

    assert event["total_tokens"] == result.stats.total_tokens

    assert event["usage_complete"] == result.stats.usage_complete

    assert event["duration_seconds"] == result.duration_seconds


def test_investigation_budget_metadata(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.return_value = final_response()

    run_agent(settings, llm, mcp)

    event = read_events(trace_stream)[0]

    assert event["event"] == "investigation_started"

    assert event["max_steps"] == settings.max_steps

    assert event["max_llm_calls"] == settings.max_llm_calls

    assert event["max_runtime"] == settings.max_runtime

    assert event["token_budget"] == settings.token_budget


def test_tool_free_finalization_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
    settings = replace(settings, max_steps=1)

    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    started = find_events(
        events,
        "llm_request_started",
    )

    completed = find_events(
        events,
        "llm_request_completed",
    )

    assert result.completed

    assert started[0]["finalization"] is False
    assert started[1]["finalization"] is True

    assert completed[0]["finalization"] is False
    assert completed[1]["finalization"] is True

    assert llm.complete.await_args.kwargs["tools"] is None


def test_unsupported_tool_name_is_sanitized(
    settings,
    llm,
    mcp,
    trace_stream,
):
    sensitive_name = "synthetic-secret-in-tool-name"

    llm.complete.side_effect = [
        tool_response(requested_call(name=sensitive_name)),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    tool_events = [event for event in events if event["event"].startswith("tool_call_")]

    assert not result.completed
    assert len(tool_events) == 2

    assert all(event["tool"] == "unsupported_tool" for event in tool_events)

    assert result.trace[0].tool == "unsupported_tool"

    assert sensitive_name not in trace_stream.getvalue()
    assert sensitive_name not in repr(result.trace)

    mcp.call_tool.assert_not_awaited()


def test_failed_tool_execution_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
    mcp.call_tool.return_value = ToolResult(
        success=False,
        payload={
            "error": "synthetic-sensitive-tool-error",
        },
    )

    llm.complete.side_effect = [
        tool_response(requested_call()),
        final_response(),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    completed = find_events(
        events,
        "tool_call_completed",
    )[0]

    assert not result.completed
    assert completed["status"] == "failed"
    assert result.stats.failed_tools == 1

    assert "synthetic-sensitive-tool-error" not in trace_stream.getvalue()


def test_tool_budget_rejection_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
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

    events = read_events(trace_stream)

    started = find_events(
        events,
        "tool_call_started",
    )

    completed = find_events(
        events,
        "tool_call_completed",
    )

    assert result.completed

    assert len(started) == 1
    assert len(completed) == 2

    assert completed[0]["status"] == "success"
    assert completed[1]["status"] == "budget_rejected"

    assert result.stats.tool_attempts == 1
    assert result.stats.successful_tools == 1
    assert mcp.call_tool.await_count == 1


@pytest.mark.parametrize(
    ("error", "status", "stop_reason"),
    [
        (
            LLMClientError("synthetic-provider-secret"),
            "provider_error",
            "llm_request_failed",
        ),
        (
            TimeoutError("synthetic-provider-secret"),
            "timeout",
            "llm_request_timeout",
        ),
    ],
)
def test_llm_failure_is_traced_without_exception_text(
    settings,
    llm,
    mcp,
    trace_stream,
    error,
    status,
    stop_reason,
):
    llm.complete.side_effect = error

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    failed = find_events(
        events,
        "llm_request_failed",
    )[0]

    assert not result.completed
    assert result.stop_reason == stop_reason

    assert failed["status"] == status
    assert failed["usage_complete"] is False

    assert events[-1]["event"] == "investigation_finished"
    assert events[-1]["completed"] is False

    assert "synthetic-provider-secret" not in trace_stream.getvalue()


def test_missing_usage_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.return_value = replace(
        tool_response(requested_call()),
        usage=None,
    )

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    failed = find_events(
        events,
        "llm_request_failed",
    )[0]

    assert not result.completed

    assert failed["status"] == "missing_token_usage"
    assert failed["usage_complete"] is False

    assert events[-1]["usage_complete"] is False


def test_llm_cancellation_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.side_effect = asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    failed = find_events(
        events,
        "llm_request_failed",
    )[0]

    assert failed["status"] == "cancelled"
    assert failed["usage_complete"] is False

    assert events[-1]["event"] == "investigation_finished"

    assert events[-1]["stop_reason"] == "investigation_cancelled"

    assert events[-1]["completed"] is False

    mcp.call_tool.assert_not_awaited()


def test_mcp_cancellation_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.return_value = tool_response(requested_call())

    mcp.call_tool.side_effect = asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    completed = find_events(
        events,
        "tool_call_completed",
    )[0]

    assert completed["status"] == "cancelled"

    assert events[-1]["event"] == "investigation_finished"

    assert events[-1]["stop_reason"] == "investigation_cancelled"

    assert events[-1]["tool_attempts"] == 1
    assert events[-1]["failed_tools"] == 1
    assert events[-1]["successful_tools"] == 0


def test_runtime_exhaustion_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
):
    settings = replace(settings, max_runtime=0)

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    assert not result.completed

    assert [event["event"] for event in events] == [
        "investigation_started",
        "investigation_finished",
    ]

    assert events[-1]["stop_reason"] == "runtime_budget_exhausted"

    assert events[-1]["llm_call"] == 0
    assert events[-1]["tool_attempts"] == 0


def test_sensitive_investigation_data_is_not_logged(
    settings,
    llm,
    mcp,
    trace_stream,
):
    sensitive_query = "synthetic-private-query"
    sensitive_argument = "synthetic-private-argument"
    sensitive_result = "synthetic-private-result"
    sensitive_diagnosis = "synthetic-private-diagnosis"

    mcp.call_tool.return_value = ToolResult(
        success=True,
        payload={"logs": sensitive_result},
    )

    llm.complete.side_effect = [
        tool_response(
            requested_call(arguments=json.dumps({"job_id": sensitive_argument}))
        ),
        final_response(sensitive_diagnosis),
    ]

    run_agent(
        settings,
        llm,
        mcp,
        query=sensitive_query,
    )

    captured = trace_stream.getvalue()

    for sensitive_value in (
        settings.llm_api_key,
        sensitive_query,
        sensitive_argument,
        sensitive_result,
        sensitive_diagnosis,
    ):
        assert sensitive_value not in captured


def test_provider_finish_reason_is_sanitized(
    settings,
    llm,
    mcp,
    trace_stream,
):
    sensitive_reason = "synthetic-private-finish-reason"

    llm.complete.side_effect = [
        tool_response(requested_call()),
        replace(
            final_response(),
            finish_reason=sensitive_reason,
        ),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    completed = find_events(
        events,
        "llm_request_completed",
    )

    assert not result.completed

    assert completed[-1]["finish_reason"] == "unknown"

    assert sensitive_reason not in trace_stream.getvalue()


@pytest.mark.parametrize(
    ("category", "http_status"),
    [
        ("authentication_error", 401),
        ("rate_limit_error", 429),
        ("provider_http_error", 503),
        ("request_timeout", None),
        ("connection_error", None),
        ("unknown_error", None),
    ],
)
def test_provider_error_metadata_is_traced(
    settings,
    llm,
    mcp,
    trace_stream,
    category,
    http_status,
):
    llm.complete.side_effect = LLMClientError(
        "synthetic-private-provider-response",
        category=category,
        http_status=http_status,
    )

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    failed = find_events(
        events,
        "llm_request_failed",
    )

    assert len(failed) == 1

    assert failed[0]["status"] == "provider_error"
    assert failed[0]["error_category"] == category
    assert failed[0]["http_status"] == http_status
    assert failed[0]["usage_complete"] is False

    assert result.completed is False
    assert result.stop_reason == "llm_request_failed"
    assert result.stats.usage_complete is False

    assert events[-1]["event"] == "investigation_finished"
    assert events[-1]["completed"] is False
    assert events[-1]["usage_complete"] is False

    assert "synthetic-private-provider-response" not in trace_stream.getvalue()

    llm.complete.assert_awaited_once()
    mcp.call_tool.assert_not_awaited()


def test_provider_failure_preserves_prior_token_accounting(
    settings,
    llm,
    mcp,
    trace_stream,
):
    llm.complete.side_effect = [
        tool_response(requested_call()),
        LLMClientError(
            "synthetic-private-provider-response",
            category="provider_http_error",
            http_status=503,
        ),
    ]

    result = run_agent(settings, llm, mcp)

    events = read_events(trace_stream)

    failed = find_events(
        events,
        "llm_request_failed",
    )[0]

    assert failed["error_category"] == "provider_http_error"
    assert failed["http_status"] == 503
    assert failed["llm_call"] == 2

    assert result.completed is False
    assert result.stop_reason == "llm_request_failed"

    assert result.stats.llm_calls == 2
    assert result.stats.tool_attempts == 1
    assert result.stats.successful_tools == 1
    assert result.stats.failed_tools == 0

    assert result.stats.prompt_tokens == 3000
    assert result.stats.completion_tokens == 50
    assert result.stats.total_tokens == 3050
    assert result.stats.usage_complete is False

    finished = events[-1]

    assert finished["event"] == "investigation_finished"
    assert finished["total_tokens"] == 3050
    assert finished["usage_complete"] is False
    assert finished["completed"] is False

    assert "synthetic-private-provider-response" not in trace_stream.getvalue()

    assert llm.complete.await_count == 2
    mcp.call_tool.assert_awaited_once()
