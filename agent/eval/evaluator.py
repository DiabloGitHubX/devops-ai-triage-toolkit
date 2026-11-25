"""Deterministic evaluation of diagnostic agent investigations.

The evaluator does not invoke an LLM, execute diagnostic tools,
or modify Kubernetes resources.

Automated matching is heuristic and requires human review.
"""

import json
import math
import re
from dataclasses import dataclass
from typing import Any

REQUIRED_SECTIONS = (
    "symptom",
    "evidence",
    "root cause",
    "suggested fix",
    "confidence",
)

ALLOWED_TOOLS = frozenset(
    {
        "list_pods",
        "describe_pod",
        "get_pod_logs",
        "list_events",
        "get_ci_log",
    }
)

COUNTED_TOOL_STATUSES = frozenset(
    {
        "success",
        "failed",
        "cancelled",
    }
)

REJECTED_TOOL_STATUSES = frozenset(
    {
        "budget_rejected",
        "runtime_rejected",
    }
)

UNKNOWN_ROOT_CAUSE = re.compile(
    r"\b(?:root cause\s+(?:is\s+)?unknown"
    r"|unknown\s*[:—–-]"
    r"|insufficient evidence"
    r"|cannot determine"
    r"|unable to determine)\b",
    re.IGNORECASE,
)

HEADING_PATTERN = re.compile(
    r"^###\s+(.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class EvaluationCheck:
    """Result of one deterministic evaluation check."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Evaluation outcome and observable execution statistics."""

    case_id: str
    passed: bool
    checks: tuple[EvaluationCheck, ...]
    exit_code: int | None
    completed: bool
    stop_reason: str
    total_tokens: int | None
    usage_complete: bool
    tool_attempts: int | None
    llm_calls: int | None
    duration_seconds: float | None
    successful_tools: tuple[str, ...]


def normalize_text(value: str) -> str:
    """Normalize case and whitespace for literal matching."""

    return " ".join(value.casefold().split())


def extract_sections(
    diagnosis: str,
) -> dict[str, str]:
    """Extract unique, ordered and nonempty diagnosis sections.

    Return an empty mapping when the format is invalid.
    """

    headings = list(HEADING_PATTERN.finditer(diagnosis))

    names = tuple(normalize_text(match.group(1)) for match in headings)

    if names != REQUIRED_SECTIONS:
        return {}

    sections: dict[str, str] = {}

    for index, match in enumerate(headings):
        end = (
            headings[index + 1].start() if index + 1 < len(headings) else len(diagnosis)
        )

        content = diagnosis[match.end() : end].strip()

        if not content:
            return {}

        sections[names[index]] = content

    return sections


def contains_literal(
    text: str,
    pattern: str,
) -> bool:
    """Match normalized text without partial-word false positives."""

    normalized_text = normalize_text(text)
    normalized_pattern = normalize_text(pattern)

    if not normalized_pattern:
        return False

    expression = re.escape(normalized_pattern)

    if normalized_pattern[0].isalnum() or normalized_pattern[0] == "_":
        expression = r"(?<!\w)" + expression

    if normalized_pattern[-1].isalnum() or normalized_pattern[-1] == "_":
        expression += r"(?!\w)"

    return re.search(expression, normalized_text) is not None


def match_concept_groups(
    text: str,
    groups: list[list[str]],
) -> tuple[bool, tuple[int, ...]]:
    """Require at least one literal match in every concept group."""

    missing = tuple(
        index
        for index, group in enumerate(groups, start=1)
        if not any(contains_literal(text, pattern) for pattern in group)
    )

    return bool(groups) and not missing, missing


def parse_trace(
    stderr: str,
) -> tuple[dict[str, Any], ...]:
    """Extract structured agent events from mixed stderr output."""

    events: list[dict[str, Any]] = []

    for line in stderr.splitlines():
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        if not isinstance(payload, dict):
            continue

        if payload.get("component") != "agent":
            continue

        event = payload.get("event")
        investigation_id = payload.get("investigation_id")

        if not isinstance(event, str) or not event:
            continue

        if not isinstance(investigation_id, str) or not investigation_id:
            continue

        events.append(payload)

    return tuple(events)


def nonnegative_int(
    value: Any,
) -> int | None:
    """Accept only genuine nonnegative integer counters."""

    if type(value) is int and value >= 0:
        return value

    return None


def positive_int(
    value: Any,
) -> int | None:
    """Accept only genuine positive integer limits."""

    if type(value) is int and value > 0:
        return value

    return None


def nonnegative_duration(
    value: Any,
) -> float | None:
    """Validate a finite nonnegative duration."""

    if type(value) not in (int, float):
        return None

    try:
        duration = float(value)
    except (OverflowError, ValueError):
        return None

    if not math.isfinite(duration) or duration < 0:
        return None

    return duration


def has_tool_status(
    event: dict[str, Any],
    allowed_statuses: frozenset[str],
) -> bool:
    """Validate a tool status before testing set membership."""

    status = event.get("status")

    return isinstance(status, str) and status in allowed_statuses


def tool_attempt_identity(
    event: dict[str, Any],
) -> tuple[int, str] | None:
    """Extract the identity of a counted diagnostic attempt."""

    step = positive_int(event.get("step"))
    tool = event.get("tool")

    if step is None or not isinstance(tool, str) or not tool:
        return None

    return step, tool


def tool_attempts_match(
    events: tuple[dict[str, Any], ...],
) -> bool:
    """Reconcile sequential starts and counted completions.

    Pre-execution rejections do not create counted attempts.
    """

    active: tuple[int, str] | None = None
    next_step = 1

    for event in events:
        event_name = event["event"]

        if event_name == "tool_call_started":
            identity = tool_attempt_identity(event)

            if active is not None or identity is None:
                return False

            if identity[0] != next_step:
                return False

            active = identity

        elif event_name == "tool_call_completed":
            if has_tool_status(event, REJECTED_TOOL_STATUSES):
                continue

            if not has_tool_status(event, COUNTED_TOOL_STATUSES):
                return False

            identity = tool_attempt_identity(event)

            if active is None or identity != active:
                return False

            active = None
            next_step += 1

    return active is None


def evaluate_case(
    case: dict[str, Any],
    diagnosis: str,
    stderr: str,
    exit_code: int | None,
) -> EvaluationResult:
    """Score a captured investigation against one evaluation case."""

    checks: list[EvaluationCheck] = []

    def add_check(
        name: str,
        passed: bool,
        detail: str,
    ) -> None:
        checks.append(
            EvaluationCheck(
                name=name,
                passed=passed,
                detail=detail,
            )
        )

    events = parse_trace(stderr)

    started = [event for event in events if event["event"] == "investigation_started"]

    finished = [event for event in events if event["event"] == "investigation_finished"]

    start = started[0] if len(started) == 1 else {}
    final = finished[0] if len(finished) == 1 else {}

    trace_valid = (
        bool(start)
        and bool(final)
        and events[0] == start
        and events[-1] == final
        and all(
            event["investigation_id"] == start["investigation_id"] for event in events
        )
    )

    completed = final.get("completed") is True

    stop_reason = final.get("stop_reason")

    if not isinstance(stop_reason, str) or not stop_reason:
        stop_reason = "missing_final_trace"

    add_check(
        "process_exit",
        type(exit_code) is int and exit_code == 0,
        f"Process exit code: {exit_code}",
    )

    add_check(
        "trace_integrity",
        trace_valid,
        "Expected one correlated investigation start and finish.",
    )

    add_check(
        "investigation_completed",
        completed and stop_reason == "diagnosis_completed",
        f"Stop reason: {stop_reason}",
    )

    sections = extract_sections(diagnosis)

    add_check(
        "diagnosis_format",
        bool(sections),
        "Expected five unique, ordered and nonempty sections.",
    )

    root_cause = sections.get("root cause", "")

    root_match, missing_root_groups = match_concept_groups(
        root_cause,
        case["root_cause_groups"],
    )

    explicitly_unknown = bool(UNKNOWN_ROOT_CAUSE.search(root_cause))

    add_check(
        "root_cause_match",
        root_match and not explicitly_unknown,
        (
            "Root cause explicitly reported as unknown."
            if explicitly_unknown
            else (
                f"Unmatched root-cause groups: {missing_root_groups}"
                if missing_root_groups
                else "All root-cause concept groups matched."
            )
        ),
    )

    evidence_match, missing_evidence_groups = match_concept_groups(
        sections.get("evidence", ""),
        case["evidence_groups"],
    )

    add_check(
        "evidence_match",
        evidence_match,
        (
            f"Unmatched evidence groups: {missing_evidence_groups}"
            if missing_evidence_groups
            else "All evidence concept groups matched."
        ),
    )

    tool_started = [event for event in events if event["event"] == "tool_call_started"]

    tool_finished = [
        event for event in events if event["event"] == "tool_call_completed"
    ]

    # Budget and runtime rejections occur before an attempt
    # is counted. Preserve them for inventory validation.
    counted_tool_finished = [
        event
        for event in tool_finished
        if has_tool_status(event, COUNTED_TOOL_STATUSES)
    ]

    tool_statuses_valid = all(
        has_tool_status(
            event,
            COUNTED_TOOL_STATUSES | REJECTED_TOOL_STATUSES,
        )
        for event in tool_finished
    )

    successful_tools = {
        event["tool"]
        for event in counted_tool_finished
        if isinstance(event.get("tool"), str) and event.get("status") == "success"
    }

    missing_tools = set(case["required_successful_tools"]) - successful_tools

    add_check(
        "required_tools",
        not missing_tools,
        (
            f"Missing successful tools: {sorted(missing_tools)}"
            if missing_tools
            else "All required diagnostic tools succeeded."
        ),
    )

    allowed_tool_inventory = all(
        isinstance(event.get("tool"), str) and event["tool"] in ALLOWED_TOOLS
        for event in (*tool_started, *tool_finished)
    )

    add_check(
        "tool_inventory",
        allowed_tool_inventory,
        "Observed tool requests must use the diagnostic allowlist.",
    )

    tool_attempts = nonnegative_int(final.get("tool_attempts"))

    successful_count = nonnegative_int(final.get("successful_tools"))

    failed_count = nonnegative_int(final.get("failed_tools"))

    max_steps = positive_int(start.get("max_steps"))

    tool_counts_valid = (
        tool_attempts is not None
        and successful_count is not None
        and failed_count is not None
        and tool_statuses_valid
        and tool_attempts == successful_count + failed_count
        and tool_attempts == len(tool_started)
        and tool_attempts == len(counted_tool_finished)
        and successful_count
        == sum(event.get("status") == "success" for event in counted_tool_finished)
        and failed_count
        == sum(
            event.get("status") in ("failed", "cancelled")
            for event in counted_tool_finished
        )
        and tool_attempts_match(events)
    )

    add_check(
        "tool_budget",
        (
            tool_counts_valid
            and max_steps is not None
            and tool_attempts is not None
            and tool_attempts <= max_steps
        ),
        (
            f"Tool attempts: {tool_attempts}/{max_steps}; "
            f"counter reconciliation: {tool_counts_valid}"
        ),
    )

    llm_calls = nonnegative_int(final.get("llm_call"))

    max_llm_calls = positive_int(start.get("max_llm_calls"))

    llm_started_count = sum(event["event"] == "llm_request_started" for event in events)

    llm_finished_count = sum(
        event["event"]
        in {
            "llm_request_completed",
            "llm_request_failed",
        }
        for event in events
    )

    add_check(
        "llm_call_budget",
        (
            llm_calls is not None
            and max_llm_calls is not None
            and 0 < llm_calls <= max_llm_calls
            and llm_calls == llm_started_count
            and llm_calls == llm_finished_count
        ),
        f"LLM calls: {llm_calls}/{max_llm_calls}",
    )

    total_tokens = nonnegative_int(final.get("total_tokens"))

    prompt_tokens = nonnegative_int(final.get("prompt_tokens"))

    completion_tokens = nonnegative_int(final.get("completion_tokens"))

    token_budget = positive_int(start.get("token_budget"))

    final_token_budget = positive_int(final.get("token_budget"))

    usage_complete = final.get("usage_complete") is True

    add_check(
        "token_accounting",
        (
            usage_complete
            and total_tokens is not None
            and prompt_tokens is not None
            and completion_tokens is not None
            and total_tokens >= prompt_tokens + completion_tokens
        ),
        f"Complete provider usage accounting: {usage_complete}",
    )

    add_check(
        "token_budget",
        (
            total_tokens is not None
            and token_budget is not None
            and token_budget == final_token_budget
            and 0 < total_tokens <= token_budget
        ),
        f"Reported tokens: {total_tokens}/{token_budget}",
    )

    duration_seconds = nonnegative_duration(final.get("duration_seconds"))

    max_runtime = positive_int(start.get("max_runtime"))

    add_check(
        "runtime_budget",
        (
            duration_seconds is not None
            and max_runtime is not None
            and duration_seconds <= max_runtime
        ),
        f"Agent runtime: {duration_seconds}/{max_runtime} seconds",
    )

    return EvaluationResult(
        case_id=case["id"],
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
        exit_code=exit_code,
        completed=completed,
        stop_reason=stop_reason,
        total_tokens=total_tokens,
        usage_complete=usage_complete,
        tool_attempts=tool_attempts,
        llm_calls=llm_calls,
        duration_seconds=duration_seconds,
        successful_tools=tuple(sorted(successful_tools)),
    )
