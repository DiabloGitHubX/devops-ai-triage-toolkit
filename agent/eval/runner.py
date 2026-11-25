"""Execute evaluation cases through the real diagnostic agent CLI.

Each case is attempted once. Failed and incomplete investigations
are retained rather than retried or replaced.
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.config import AgentSettings, load_settings
from agent.eval.evaluator import (
    ALLOWED_TOOLS,
    EvaluationCheck,
    EvaluationResult,
    evaluate_case,
    parse_trace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CASES_PATH = Path(__file__).with_name("cases.json")

ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts" / "eval"

PROCESS_GRACE_SECONDS = 30

MAX_CAPTURE_BYTES = 1024 * 1024

MAX_DATASET_BYTES = 128 * 1024

CASE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

EXPECTED_CASE_FIELDS = frozenset(
    {
        "id",
        "category",
        "description",
        "arguments",
        "expected_root_cause",
        "root_cause_groups",
        "evidence_groups",
        "required_successful_tools",
    }
)


class EvaluationRunnerError(RuntimeError):
    """Invalid evaluation configuration or dataset."""


@dataclass(frozen=True, slots=True)
class CaseExecution:
    """Captured subprocess outcome and automated evaluation."""

    case_id: str
    category: str
    evaluation: EvaluationResult
    wall_time_seconds: float
    timed_out: bool
    capture_truncated: bool
    execution_error: str | None
    diagnosis_path: str
    trace_path: str


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """One evaluation run containing all attempted cases."""

    run_id: str
    output_directory: Path
    started_at: str
    finished_at: str
    model: str
    limits: dict[str, int]
    cases: tuple[CaseExecution, ...]


def nonempty_string(value: Any) -> bool:
    """Check whether a value is a nonempty string."""

    return isinstance(value, str) and bool(value.strip())


def validate_groups(value: Any) -> bool:
    """Validate required concept groups and their alternatives."""

    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(group, list)
            and bool(group)
            and all(nonempty_string(item) for item in group)
            for group in value
        )
    )


def validate_case(
    case: Any,
) -> None:
    """Validate a case before using it to launch a process."""

    if not isinstance(case, dict):
        raise EvaluationRunnerError("Evaluation cases must be objects.")

    if set(case) != EXPECTED_CASE_FIELDS:
        raise EvaluationRunnerError("Unexpected evaluation case fields.")

    case_id = case["id"]

    if not isinstance(case_id, str) or CASE_ID_PATTERN.fullmatch(case_id) is None:
        raise EvaluationRunnerError("Invalid evaluation case identifier.")

    if case["category"] not in ("kubernetes", "ci"):
        raise EvaluationRunnerError("Unsupported evaluation case category.")

    for field in (
        "description",
        "expected_root_cause",
    ):
        if not nonempty_string(case[field]):
            raise EvaluationRunnerError("Missing evaluation case description.")

    for field in (
        "root_cause_groups",
        "evidence_groups",
    ):
        if not validate_groups(case[field]):
            raise EvaluationRunnerError("Invalid evaluation concept groups.")

    tools = case["required_successful_tools"]

    if (
        not isinstance(tools, list)
        or not tools
        or not all(isinstance(tool, str) and tool in ALLOWED_TOOLS for tool in tools)
        or len(tools) != len(set(tools))
    ):
        raise EvaluationRunnerError("Invalid required diagnostic tools.")

    arguments = case["arguments"]

    if not isinstance(arguments, list) or not all(
        nonempty_string(argument) for argument in arguments
    ):
        raise EvaluationRunnerError("Invalid evaluation CLI arguments.")

    # Restrict this dataset to the two supported diagnostic
    # target forms. Expected answers are never passed to
    # the agent as arguments or environment variables.
    if case["category"] == "ci":
        valid = (
            len(arguments) == 2
            and arguments[0] == "--ci"
            and re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}",
                arguments[1],
            )
            is not None
        )

    else:
        valid = (
            len(arguments) == 4
            and arguments[:3] == ["--namespace", "staging", "--pod"]
            and re.fullmatch(
                r"[a-z0-9][a-z0-9.-]{0,252}",
                arguments[3],
            )
            is not None
        )

    if not valid:
        raise EvaluationRunnerError("Unsupported evaluation argument structure.")


def load_cases(
    path: Path = CASES_PATH,
) -> tuple[dict[str, Any], ...]:
    """Load and validate the bounded evaluation dataset."""

    try:
        with path.open("rb") as file:
            raw = file.read(MAX_DATASET_BYTES + 1)

        if len(raw) > MAX_DATASET_BYTES:
            raise EvaluationRunnerError("Evaluation dataset exceeds its size limit.")

        dataset = json.loads(raw.decode("utf-8"))

    except (OSError, UnicodeError, ValueError):
        raise EvaluationRunnerError("Unable to read the evaluation dataset.") from None

    if (
        not isinstance(dataset, dict)
        or type(dataset.get("schema_version")) is not int
        or dataset["schema_version"] != 1
    ):
        raise EvaluationRunnerError("Unsupported evaluation dataset schema.")

    cases = dataset.get("cases")

    if not isinstance(cases, list) or not cases or len(cases) > 50:
        raise EvaluationRunnerError("Invalid number of evaluation cases.")

    identifiers: set[str] = set()

    for case in cases:
        validate_case(case)

        case_id = case["id"]

        if case_id in identifiers:
            raise EvaluationRunnerError("Duplicate evaluation case identifier.")

        identifiers.add(case_id)

    return tuple(cases)


def configured_limits(
    settings: AgentSettings,
) -> dict[str, int]:
    """Return public execution limits without credentials."""

    return {
        "max_steps": settings.max_steps,
        "max_llm_calls": settings.max_llm_calls,
        "max_runtime": settings.max_runtime,
        "token_budget": settings.token_budget,
    }


def build_agent_environment(
    settings: AgentSettings,
) -> dict[str, str]:
    """Freeze the effective agent configuration for this run."""

    environment = os.environ.copy()

    environment.update(
        {
            "LLM_BASE_URL": settings.llm_base_url,
            "LLM_API_KEY": settings.llm_api_key,
            "LLM_MODEL": settings.llm_model,
            "AGENT_MAX_STEPS": str(settings.max_steps),
            "AGENT_TOKEN_BUDGET": str(settings.token_budget),
            "AGENT_MAX_LLM_CALLS": str(settings.max_llm_calls),
            "AGENT_MAX_OUTPUT_TOKENS": str(settings.max_output_tokens),
            "AGENT_LLM_TIMEOUT": str(settings.llm_timeout),
            "AGENT_MCP_TIMEOUT": str(settings.mcp_timeout),
            "AGENT_MAX_RUNTIME": str(settings.max_runtime),
            "AGENT_DEFAULT_NAMESPACE": (settings.default_namespace),
            "PYTHONIOENCODING": "utf-8",
        }
    )

    return environment


def create_run_directory(
    root: Path = ARTIFACTS_ROOT,
) -> tuple[str, Path]:
    """Create a unique directory without overwriting old runs."""

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    run_id = f"{timestamp}-{uuid4().hex[:8]}"

    directory = root / run_id

    directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    (directory / "cases").mkdir()

    return run_id, directory


def read_capture(
    path: Path,
) -> tuple[str, bool]:
    """Bound the amount of captured output loaded for scoring."""

    with path.open("rb") as file:
        raw = file.read(MAX_CAPTURE_BYTES + 1)

    truncated = len(raw) > MAX_CAPTURE_BYTES

    text = raw[:MAX_CAPTURE_BYTES].decode(
        "utf-8",
        errors="replace",
    )

    return text, truncated


def configuration_matches(
    stderr: str,
    expected_limits: dict[str, int],
) -> bool:
    """Check observed trace limits against the run configuration."""

    starts = [
        event
        for event in parse_trace(stderr)
        if event["event"] == "investigation_started"
    ]

    if len(starts) != 1:
        return False

    start = starts[0]

    return all(
        type(start.get(name)) is int and start[name] == expected
        for name, expected in expected_limits.items()
    )


def append_execution_checks(
    result: EvaluationResult,
    checks: tuple[EvaluationCheck, ...],
) -> EvaluationResult:
    """Combine diagnosis checks with subprocess-level checks."""

    combined = result.checks + checks

    return replace(
        result,
        checks=combined,
        passed=all(check.passed for check in combined),
    )


def run_case(
    case: dict[str, Any],
    settings: AgentSettings,
    output_directory: Path,
) -> CaseExecution:
    """Execute and score one case without automatic retries."""

    validate_case(case)

    case_id = case["id"]

    cases_directory = output_directory / "cases"

    diagnosis_path = cases_directory / f"{case_id}.txt"

    trace_path = cases_directory / f"{case_id}.trace.jsonl"

    command = [
        sys.executable,
        "-m",
        "agent",
        *case["arguments"],
    ]

    timeout_seconds = settings.max_runtime + PROCESS_GRACE_SECONDS

    exit_code: int | None = None

    timed_out = False

    execution_error: str | None = None

    started = time.monotonic()

    with (
        diagnosis_path.open("xb") as stdout_file,
        trace_path.open("xb") as stderr_file,
    ):
        try:
            process = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=build_agent_environment(settings),
                stdout=stdout_file,
                stderr=stderr_file,
                stdin=subprocess.DEVNULL,
                shell=False,
                timeout=timeout_seconds,
                check=False,
            )

            exit_code = process.returncode

        except subprocess.TimeoutExpired:
            timed_out = True
            execution_error = "process_timeout"

        except OSError:
            execution_error = "process_launch_failed"

    wall_time = round(
        time.monotonic() - started,
        3,
    )

    diagnosis, diagnosis_truncated = read_capture(diagnosis_path)

    stderr, trace_truncated = read_capture(trace_path)

    capture_truncated = diagnosis_truncated or trace_truncated

    result = evaluate_case(
        case=case,
        diagnosis=diagnosis,
        stderr=stderr,
        exit_code=exit_code,
    )

    execution_checks = (
        EvaluationCheck(
            name="subprocess_execution",
            passed=execution_error is None,
            detail=execution_error or "Process returned.",
        ),
        EvaluationCheck(
            name="subprocess_timeout",
            passed=(not timed_out and wall_time <= timeout_seconds),
            detail=(f"Wall time: {wall_time}/{timeout_seconds} seconds"),
        ),
        EvaluationCheck(
            name="capture_size",
            passed=not capture_truncated,
            detail=(
                "Capture exceeds evaluation size limit."
                if capture_truncated
                else "Captured output within evaluation limits."
            ),
        ),
        EvaluationCheck(
            name="configuration_consistency",
            passed=configuration_matches(
                stderr,
                configured_limits(settings),
            ),
            detail=("Observed limits must match the evaluation run configuration."),
        ),
    )

    result = append_execution_checks(
        result,
        execution_checks,
    )

    return CaseExecution(
        case_id=case_id,
        category=case["category"],
        evaluation=result,
        wall_time_seconds=wall_time,
        timed_out=timed_out,
        capture_truncated=capture_truncated,
        execution_error=execution_error,
        diagnosis_path=diagnosis_path.relative_to(output_directory).as_posix(),
        trace_path=trace_path.relative_to(output_directory).as_posix(),
    )


def run_evaluation(
    cases_path: Path = CASES_PATH,
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> EvaluationRun:
    """Execute every configured case exactly once."""

    cases = load_cases(cases_path)

    settings = load_settings()

    run_id, output_directory = create_run_directory(artifacts_root)

    started_at = datetime.now(UTC).isoformat()

    results: list[CaseExecution] = []

    for case in cases:
        result = run_case(
            case=case,
            settings=settings,
            output_directory=output_directory,
        )

        results.append(result)

    return EvaluationRun(
        run_id=run_id,
        output_directory=output_directory,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
        model=settings.llm_model,
        limits=configured_limits(settings),
        cases=tuple(results),
    )
