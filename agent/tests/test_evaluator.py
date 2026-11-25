"""Regression tests for deterministic investigation evaluation."""

import pytest

from agent.eval.evaluator import evaluate_case
from agent.tests.eval_helpers import (
    DIAGNOSIS,
    make_case,
    make_event,
    make_trace_events,
    serialize_trace,
)


def score(
    diagnosis=DIAGNOSIS,
    events=None,
    exit_code=0,
    case=None,
):
    """Evaluate an isolated synthetic investigation."""

    return evaluate_case(
        case=make_case() if case is None else case,
        diagnosis=diagnosis,
        stderr=serialize_trace(make_trace_events() if events is None else events),
        exit_code=exit_code,
    )


def get_check(result, name):
    """Retrieve an individual evaluation check."""

    return next(check for check in result.checks if check.name == name)


def assert_failed(result, check_name):
    """Assert that a specific failure prevents an overall pass."""

    assert not result.passed
    assert not get_check(result, check_name).passed


def test_successful_investigation():
    result = score()

    assert result.passed
    assert result.completed
    assert len(result.checks) == 13
    assert all(check.passed for check in result.checks)
    assert result.exit_code == 0
    assert result.stop_reason == "diagnosis_completed"
    assert result.total_tokens == 3500
    assert result.usage_complete
    assert result.tool_attempts == 1
    assert result.llm_calls == 2
    assert result.duration_seconds == 2.5
    assert result.successful_tools == ("get_ci_log",)


@pytest.mark.parametrize(
    "exit_code",
    [1, 2, 3, 130, -1, None, True, False, "0"],
)
def test_unsuccessful_process_exit(exit_code):
    result = score(exit_code=exit_code)

    assert_failed(result, "process_exit")


def test_incomplete_investigation():
    events = make_trace_events()

    events[-1]["completed"] = False
    events[-1]["stop_reason"] = "llm_request_failed"

    result = score(events=events)

    assert_failed(result, "investigation_completed")


def test_unexpected_stop_reason():
    events = make_trace_events()

    events[-1]["stop_reason"] = "token_budget_exhausted"

    result = score(events=events)

    assert_failed(result, "investigation_completed")


@pytest.mark.parametrize(
    "heading",
    [
        "Symptom",
        "Evidence",
        "Root cause",
        "Suggested fix",
        "Confidence",
    ],
)
def test_missing_required_heading(heading):
    diagnosis = DIAGNOSIS.replace(
        f"### {heading}",
        f"### Missing {heading}",
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "diagnosis_format")


def test_empty_diagnosis():
    result = score(diagnosis="")

    assert_failed(result, "diagnosis_format")


def test_duplicate_heading():
    diagnosis = DIAGNOSIS + "\n### Evidence\nDuplicate evidence."

    result = score(diagnosis=diagnosis)

    assert_failed(result, "diagnosis_format")


def test_unexpected_heading():
    diagnosis = DIAGNOSIS + "\n### Additional information\nUnexpected section."

    result = score(diagnosis=diagnosis)

    assert_failed(result, "diagnosis_format")


def test_reordered_headings():
    diagnosis = (
        DIAGNOSIS.replace(
            "### Symptom",
            "### Temporary",
        )
        .replace(
            "### Evidence",
            "### Symptom",
        )
        .replace(
            "### Temporary",
            "### Evidence",
        )
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "diagnosis_format")


def test_empty_section():
    diagnosis = DIAGNOSIS.replace(
        "### Confidence\nHigh.",
        "### Confidence\n",
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "diagnosis_format")


def test_case_insensitive_concept_matching():
    result = score(diagnosis=DIAGNOSIS.upper())

    assert result.passed


def test_incorrect_root_cause():
    diagnosis = DIAGNOSIS.replace(
        "The application accepts negative payment amounts because\n"
        "negative amount validation is missing.",
        "The CI runner lost network connectivity.",
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "root_cause_match")


@pytest.mark.parametrize(
    "unknown_cause",
    [
        "Unknown — insufficient evidence.",
        "Root cause is unknown.",
        "Cannot determine the root cause.",
        "Unable to determine the root cause.",
    ],
)
def test_unknown_root_cause(unknown_cause):
    diagnosis = DIAGNOSIS.replace(
        "The application accepts negative payment amounts because\n"
        "negative amount validation is missing.",
        unknown_cause,
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "root_cause_match")


def test_unknown_cause_with_matching_keywords():
    diagnosis = DIAGNOSIS.replace(
        "The application accepts negative payment amounts because\n"
        "negative amount validation is missing.",
        "Unknown — insufficient evidence. Negative payment validation may be involved.",
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "root_cause_match")


def test_root_cause_keywords_in_wrong_section():
    diagnosis = DIAGNOSIS.replace(
        "The application accepts negative payment amounts because\n"
        "negative amount validation is missing.",
        "The build infrastructure failed.",
    )

    # The suggested fix still contains negative payment
    # terminology, but the root-cause section does not.
    result = score(diagnosis=diagnosis)

    assert_failed(result, "root_cause_match")


def test_missing_evidence():
    diagnosis = DIAGNOSIS.replace(
        "E   assert 201 == 400",
        "An assertion failed.",
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "evidence_match")


def test_evidence_in_wrong_section():
    diagnosis = DIAGNOSIS.replace(
        "E   assert 201 == 400",
        "An assertion failed.",
    ).replace(
        "### Suggested fix",
        "### Suggested fix\nObserved assertion: 201 == 400",
    )

    result = score(diagnosis=diagnosis)

    assert_failed(result, "evidence_match")


def test_missing_trace():
    result = score(events=[])

    assert_failed(result, "trace_integrity")


def test_missing_start_event():
    events = make_trace_events()[1:]

    result = score(events=events)

    assert_failed(result, "trace_integrity")


def test_missing_finish_event():
    events = make_trace_events()[:-1]

    result = score(events=events)

    assert_failed(result, "trace_integrity")


def test_duplicate_start_event():
    events = make_trace_events()

    events.insert(0, events[0].copy())

    result = score(events=events)

    assert_failed(result, "trace_integrity")


def test_duplicate_finish_event():
    events = make_trace_events()

    events.append(events[-1].copy())

    result = score(events=events)

    assert_failed(result, "trace_integrity")


def test_mismatched_investigation_identifier():
    events = make_trace_events()

    events[3]["investigation_id"] = "different-investigation"

    result = score(events=events)

    assert_failed(result, "trace_integrity")


def test_event_after_investigation_finished():
    events = make_trace_events()

    events.append(make_event("llm_request_started", llm_call=3))

    result = score(events=events)

    assert_failed(result, "trace_integrity")


def test_mixed_stderr_output():
    stderr = (
        "MCP server starting\n"
        "{invalid JSON}\n"
        + serialize_trace(make_trace_events())
        + "MCP server shutting down\n"
    )

    result = evaluate_case(
        case=make_case(),
        diagnosis=DIAGNOSIS,
        stderr=stderr,
        exit_code=0,
    )

    assert result.passed


def test_missing_required_tool():
    case = make_case()

    case["required_successful_tools"] = [
        "describe_pod",
    ]

    result = score(case=case)

    assert_failed(result, "required_tools")


def test_unsupported_tool():
    events = make_trace_events()

    events[3]["tool"] = "delete_pod"
    events[4]["tool"] = "delete_pod"

    result = score(events=events)

    assert_failed(result, "tool_inventory")


@pytest.mark.parametrize(
    "status",
    ["budget_rejected", "runtime_rejected"],
)
def test_pre_execution_rejection_accounting(status):
    events = make_trace_events()

    events.insert(
        -1,
        make_event(
            "tool_call_completed",
            tool="get_ci_log",
            status=status,
        ),
    )

    result = score(events=events)

    assert get_check(result, "tool_budget").passed
    assert result.tool_attempts == 1


def test_unsupported_rejected_tool():
    events = make_trace_events()

    events.insert(
        -1,
        make_event(
            "tool_call_completed",
            tool="delete_pod",
            status="budget_rejected",
        ),
    )

    result = score(events=events)

    assert_failed(result, "tool_inventory")


@pytest.mark.parametrize(
    "status",
    ["failed", "cancelled"],
)
def test_failed_attempt_accounting(status):
    events = make_trace_events()

    events[4]["status"] = status

    events[-1]["successful_tools"] = 0
    events[-1]["failed_tools"] = 1

    result = score(events=events)

    assert get_check(result, "tool_budget").passed
    assert_failed(result, "required_tools")


@pytest.mark.parametrize(
    "status",
    [
        "unexpected_status",
        None,
        [],
        {},
        True,
        123,
    ],
)
def test_invalid_tool_completion_status(status):
    events = make_trace_events()

    events[4]["status"] = status

    result = score(events=events)

    assert_failed(result, "tool_budget")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step", 2),
        ("step", True),
        ("step", 0),
        ("step", -1),
        ("step", None),
        ("tool", "list_pods"),
    ],
)
def test_mismatched_tool_identity(field, value):
    events = make_trace_events()

    events[4][field] = value

    result = score(events=events)

    assert_failed(result, "tool_budget")


def test_missing_tool_completion():
    events = make_trace_events()

    del events[4]

    result = score(events=events)

    assert_failed(result, "tool_budget")


def test_duplicate_tool_completion():
    events = make_trace_events()

    events.insert(5, events[4].copy())

    result = score(events=events)

    assert_failed(result, "tool_budget")


def test_duplicate_tool_start():
    events = make_trace_events()

    events.insert(4, events[3].copy())

    result = score(events=events)

    assert_failed(result, "tool_budget")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_attempts", 0),
        ("tool_attempts", 2),
        ("tool_attempts", 11),
        ("tool_attempts", True),
        ("successful_tools", 0),
        ("successful_tools", 2),
        ("failed_tools", 1),
        ("failed_tools", -1),
    ],
)
def test_inconsistent_tool_counters(field, value):
    events = make_trace_events()

    events[-1][field] = value

    result = score(events=events)

    assert_failed(result, "tool_budget")


def test_tool_budget_exceeded():
    events = make_trace_events()

    events[0]["max_steps"] = 0

    result = score(events=events)

    assert_failed(result, "tool_budget")


@pytest.mark.parametrize(
    "llm_calls",
    [0, 1, 3, 13, True, None, -1],
)
def test_invalid_llm_call_accounting(llm_calls):
    events = make_trace_events()

    events[-1]["llm_call"] = llm_calls

    result = score(events=events)

    assert_failed(result, "llm_call_budget")


def test_llm_call_budget_exceeded():
    events = make_trace_events()

    events[0]["max_llm_calls"] = 1

    result = score(events=events)

    assert_failed(result, "llm_call_budget")


def test_missing_llm_completion():
    events = make_trace_events()

    del events[6]

    result = score(events=events)

    assert_failed(result, "llm_call_budget")


@pytest.mark.parametrize(
    "usage_complete",
    [False, None, 0, 1, "true"],
)
def test_incomplete_token_accounting(usage_complete):
    events = make_trace_events()

    events[-1]["usage_complete"] = usage_complete

    result = score(events=events)

    assert_failed(result, "token_accounting")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_tokens", -1),
        ("prompt_tokens", None),
        ("prompt_tokens", True),
        ("completion_tokens", -1),
        ("completion_tokens", "500"),
        ("total_tokens", -1),
        ("total_tokens", None),
        ("total_tokens", True),
        ("total_tokens", 3499),
    ],
)
def test_invalid_token_accounting(field, value):
    events = make_trace_events()

    events[-1][field] = value

    result = score(events=events)

    assert_failed(result, "token_accounting")


def test_token_budget_exceeded():
    events = make_trace_events()

    events[-1]["total_tokens"] = 30001

    result = score(events=events)

    assert_failed(result, "token_budget")


def test_token_budget_mismatch():
    events = make_trace_events()

    events[-1]["token_budget"] = 40000

    result = score(events=events)

    assert_failed(result, "token_budget")


def test_exact_token_budget_boundary():
    events = make_trace_events()

    events[0]["token_budget"] = 3500
    events[-1]["token_budget"] = 3500

    result = score(events=events)

    assert result.passed


@pytest.mark.parametrize(
    "duration",
    [-1, 301, None, True, "2.5"],
)
def test_invalid_runtime(duration):
    events = make_trace_events()

    events[-1]["duration_seconds"] = duration

    result = score(events=events)

    assert_failed(result, "runtime_budget")


def test_exact_runtime_budget_boundary():
    events = make_trace_events()

    events[-1]["duration_seconds"] = 300

    result = score(events=events)

    assert result.passed
