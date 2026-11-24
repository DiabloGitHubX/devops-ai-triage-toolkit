"""Structured, credential-safe execution tracing for the diagnostic agent."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

LOGGER_NAME = "triage.agent"

ALLOWED_EVENTS = frozenset(
    {
        "investigation_started",
        "llm_request_started",
        "llm_request_completed",
        "llm_request_failed",
        "tool_call_started",
        "tool_call_completed",
        "investigation_finished",
    }
)

ALLOWED_FIELDS = frozenset(
    {
        "step",
        "tool",
        "purpose",
        "status",
        "error_category",
        "http_status",
        "duration_seconds",
        "llm_call",
        "tool_count",
        "tool_attempts",
        "successful_tools",
        "failed_tools",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "token_budget",
        "max_steps",
        "max_llm_calls",
        "max_runtime",
        "usage_complete",
        "stop_reason",
        "completed",
        "finish_reason",
        "finalization",
    }
)


class JSONTraceFormatter(logging.Formatter):
    """Serialize structured execution events as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "trace_event", None)

        if not isinstance(event, dict):
            event = {"event": "unstructured_log"}

        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=UTC,
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": "agent",
            **event,
        }

        return json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )


def configure_trace_logging() -> logging.Logger:
    """Configure an isolated JSON logger writing to stderr."""

    logger = logging.getLogger(LOGGER_NAME)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONTraceFormatter())

    logger.addHandler(handler)

    return logger


class InvestigationTracer:
    """Emit correlated execution events for one investigation."""

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:
        self.investigation_id = uuid4().hex
        self._logger = logger if logger is not None else logging.getLogger(LOGGER_NAME)

    def emit(
        self,
        event: str,
        **fields: Any,
    ) -> None:
        """Emit an event containing only approved metadata fields."""

        if event not in ALLOWED_EVENTS:
            raise ValueError("Unsupported trace event.")

        if fields.keys() - ALLOWED_FIELDS:
            raise ValueError("Unsupported trace metadata field.")

        for value in fields.values():
            if value is not None and type(value) not in (
                str,
                int,
                float,
                bool,
            ):
                raise ValueError("Trace metadata must contain scalar values.")

        payload = {
            "event": event,
            "investigation_id": self.investigation_id,
            **fields,
        }

        self._logger.info(
            "agent_trace",
            extra={"trace_event": payload},
        )
