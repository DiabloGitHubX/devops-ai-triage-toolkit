"""Regression tests for the evaluation subprocess runner."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.eval.evaluator import (
    EvaluationCheck,
    evaluate_case,
)
from agent.eval.runner import (
    MAX_CAPTURE_BYTES,
    PROCESS_GRACE_SECONDS,
    PROJECT_ROOT,
    append_execution_checks,
    build_agent_environment,
    configuration_matches,
    configured_limits,
    create_run_directory,
    read_capture,
    run_case,
    run_evaluation,
)
from agent.tests.eval_helpers import (
    DIAGNOSIS,
    LIMITS,
    make_case,
    make_trace,
    make_trace_events,
    serialize_trace,
)


@pytest.fixture
def eval_settings(settings):
    """Align synthetic settings with the evaluation trace."""

    return replace(
        settings,
        token_budget=30000,
    )


@pytest.fixture
def run_directory(tmp_path):
    """Create an isolated evaluation artifact directory."""

    _, directory = create_run_directory(tmp_path)

    return directory


def get_check(result, name):
    """Retrieve a subprocess-level evaluation check."""

    return next(check for check in result.evaluation.checks if check.name == name)


def successful_process(command, **kwargs):
    """Simulate a successful diagnostic agent process."""

    kwargs["stdout"].write(DIAGNOSIS.encode("utf-8"))

    kwargs["stderr"].write(make_trace().encode("utf-8"))

    return subprocess.CompletedProcess(
        args=command,
        returncode=0,
    )


def test_configured_limits(eval_settings):
    limits = configured_limits(eval_settings)

    assert limits == LIMITS

    assert "llm_api_key" not in limits

    assert "LLM_API_KEY" not in limits


def test_agent_environment(eval_settings):
    environment = build_agent_environment(eval_settings)

    expected = {
        "LLM_BASE_URL": eval_settings.llm_base_url,
        "LLM_API_KEY": eval_settings.llm_api_key,
        "LLM_MODEL": eval_settings.llm_model,
        "AGENT_MAX_STEPS": "10",
        "AGENT_TOKEN_BUDGET": "30000",
        "AGENT_MAX_LLM_CALLS": "12",
        "AGENT_MAX_OUTPUT_TOKENS": "2048",
        "AGENT_LLM_TIMEOUT": "60",
        "AGENT_MCP_TIMEOUT": "45",
        "AGENT_MAX_RUNTIME": "300",
        "AGENT_DEFAULT_NAMESPACE": "staging",
        "PYTHONIOENCODING": "utf-8",
    }

    for name, value in expected.items():
        assert environment[name] == value


def test_effective_settings_override_environment(
    eval_settings,
    monkeypatch,
):
    monkeypatch.setenv(
        "AGENT_TOKEN_BUDGET",
        "99999",
    )

    monkeypatch.setenv(
        "LLM_MODEL",
        "different-model",
    )

    environment = build_agent_environment(eval_settings)

    assert environment["AGENT_TOKEN_BUDGET"] == "30000"

    assert environment["LLM_MODEL"] == (eval_settings.llm_model)


def test_environment_is_not_modified(
    eval_settings,
    monkeypatch,
):
    monkeypatch.setenv(
        "AGENT_TOKEN_BUDGET",
        "12345",
    )

    build_agent_environment(eval_settings)

    import os

    assert os.environ["AGENT_TOKEN_BUDGET"] == "12345"


def test_unique_run_directories(tmp_path):
    first_id, first = create_run_directory(tmp_path)

    second_id, second = create_run_directory(tmp_path)

    assert first_id != second_id
    assert first != second

    assert first.is_dir()
    assert second.is_dir()

    assert (first / "cases").is_dir()
    assert (second / "cases").is_dir()


def test_existing_artifacts_preserved(tmp_path):
    _, first = create_run_directory(tmp_path)

    artifact = first / "cases" / "existing.txt"

    artifact.write_text(
        "Preserve this artifact.",
        encoding="utf-8",
    )

    create_run_directory(tmp_path)

    assert artifact.read_text(encoding="utf-8") == "Preserve this artifact."


@pytest.mark.parametrize(
    "size",
    [
        0,
        100,
        MAX_CAPTURE_BYTES - 1,
        MAX_CAPTURE_BYTES,
    ],
)
def test_capture_within_limit(tmp_path, size):
    path = tmp_path / "capture.txt"

    path.write_bytes(b"x" * size)

    text, truncated = read_capture(path)

    assert not truncated

    assert len(text) == size


@pytest.mark.parametrize(
    "extra_bytes",
    [1, 100, 4096],
)
def test_oversized_capture(tmp_path, extra_bytes):
    path = tmp_path / "capture.txt"

    path.write_bytes(b"x" * (MAX_CAPTURE_BYTES + extra_bytes))

    text, truncated = read_capture(path)

    assert truncated

    assert len(text) == MAX_CAPTURE_BYTES


def test_utf8_capture(tmp_path):
    path = tmp_path / "capture.txt"

    expected = "Unknown — insufficient evidence."

    path.write_bytes(expected.encode("utf-8"))

    text, truncated = read_capture(path)

    assert text == expected

    assert not truncated


def test_invalid_utf8_capture(tmp_path):
    path = tmp_path / "capture.txt"

    path.write_bytes(b"\xff\xfe")

    text, truncated = read_capture(path)

    assert "\ufffd" in text

    assert not truncated


def test_configuration_matches():
    assert configuration_matches(
        make_trace(),
        LIMITS,
    )


@pytest.mark.parametrize(
    "field",
    [
        "max_steps",
        "max_llm_calls",
        "max_runtime",
        "token_budget",
    ],
)
def test_configuration_mismatch(field):
    events = make_trace_events()

    events[0][field] += 1

    assert not configuration_matches(
        serialize_trace(events),
        LIMITS,
    )


@pytest.mark.parametrize(
    "value",
    [None, True, "30000", -1],
)
def test_invalid_configuration_trace_value(value):
    events = make_trace_events()

    events[0]["token_budget"] = value

    assert not configuration_matches(
        serialize_trace(events),
        LIMITS,
    )


def test_missing_configuration_trace():
    assert not configuration_matches(
        "",
        LIMITS,
    )


def test_duplicate_configuration_trace():
    events = make_trace_events()

    events.insert(0, events[0].copy())

    assert not configuration_matches(
        serialize_trace(events),
        LIMITS,
    )


def test_missing_configuration_field():
    events = make_trace_events()

    del events[0]["max_runtime"]

    assert not configuration_matches(
        serialize_trace(events),
        LIMITS,
    )


@pytest.mark.parametrize(
    "passed",
    [True, False],
)
def test_append_execution_checks(passed):
    baseline = evaluate_case(
        case=make_case(),
        diagnosis=DIAGNOSIS,
        stderr=make_trace(),
        exit_code=0,
    )

    result = append_execution_checks(
        baseline,
        (
            EvaluationCheck(
                name="synthetic_execution_check",
                passed=passed,
                detail="Synthetic check.",
            ),
        ),
    )

    assert baseline.passed
    assert len(baseline.checks) == 13

    assert result.passed is passed
    assert len(result.checks) == 14


def test_successful_case_execution(
    eval_settings,
    run_directory,
):
    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=successful_process,
    ) as mocked:
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert mocked.call_count == 1

    assert result.evaluation.passed

    assert len(result.evaluation.checks) == 17

    assert result.evaluation.exit_code == 0

    assert not result.timed_out

    assert not result.capture_truncated

    assert result.execution_error is None

    assert result.wall_time_seconds >= 0

    assert result.case_id == "ci-test-failure"

    assert result.category == "ci"


def test_subprocess_invocation(
    eval_settings,
    run_directory,
):
    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=successful_process,
    ) as mocked:
        run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    args, kwargs = mocked.call_args

    assert args[0] == [
        sys.executable,
        "-m",
        "agent",
        "--ci",
        "build-1423",
    ]

    assert kwargs["cwd"] == PROJECT_ROOT

    assert kwargs["shell"] is False

    assert kwargs["check"] is False

    assert kwargs["stdin"] == subprocess.DEVNULL

    assert kwargs["timeout"] == (eval_settings.max_runtime + PROCESS_GRACE_SECONDS)

    assert kwargs["env"]["AGENT_TOKEN_BUDGET"] == "30000"

    assert eval_settings.llm_api_key not in args[0]

    assert make_case()["expected_root_cause"] not in args[0]


def test_artifact_persistence(
    eval_settings,
    run_directory,
):
    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=successful_process,
    ):
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    diagnosis = run_directory / result.diagnosis_path

    trace = run_directory / result.trace_path

    assert diagnosis.read_text(encoding="utf-8") == DIAGNOSIS

    assert trace.read_text(encoding="utf-8") == make_trace()

    assert not Path(result.diagnosis_path).is_absolute()

    assert not Path(result.trace_path).is_absolute()


def test_timeout_without_retry(
    eval_settings,
    run_directory,
):
    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=subprocess.TimeoutExpired(
            cmd=["python", "-m", "agent"],
            timeout=330,
        ),
    ) as mocked:
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert mocked.call_count == 1

    assert result.timed_out

    assert result.execution_error == "process_timeout"

    assert result.evaluation.exit_code is None

    assert not result.evaluation.passed

    assert not get_check(
        result,
        "subprocess_timeout",
    ).passed


def test_timeout_preserves_partial_output(
    eval_settings,
    run_directory,
):
    def timed_out_process(command, **kwargs):
        kwargs["stdout"].write(b"Partial diagnostic output.")

        kwargs["stderr"].write(b"Partial trace output.")

        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=330,
        )

    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=timed_out_process,
    ):
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert result.timed_out

    assert (
        run_directory / result.diagnosis_path
    ).read_bytes() == b"Partial diagnostic output."

    assert (run_directory / result.trace_path).read_bytes() == b"Partial trace output."


def test_launch_failure_without_retry(
    eval_settings,
    run_directory,
):
    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=OSError("Synthetic launch failure"),
    ) as mocked:
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert mocked.call_count == 1

    assert result.execution_error == "process_launch_failed"

    assert not result.timed_out

    assert not result.evaluation.passed

    assert not get_check(
        result,
        "subprocess_execution",
    ).passed


@pytest.mark.parametrize(
    "exit_code",
    [1, 2, 3, 130, -1],
)
def test_nonzero_exit_retained(
    eval_settings,
    run_directory,
    exit_code,
):
    def failed_process(command, **kwargs):
        successful_process(command, **kwargs)

        return subprocess.CompletedProcess(
            args=command,
            returncode=exit_code,
        )

    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=failed_process,
    ) as mocked:
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert mocked.call_count == 1

    assert result.evaluation.exit_code == exit_code

    assert not result.evaluation.passed

    assert result.execution_error is None

    assert get_check(
        result,
        "subprocess_execution",
    ).passed


def test_configuration_mismatch_fails_case(
    eval_settings,
    run_directory,
):
    events = make_trace_events()

    events[0]["token_budget"] = 20000
    events[-1]["token_budget"] = 20000

    def mismatched_process(command, **kwargs):
        kwargs["stdout"].write(DIAGNOSIS.encode("utf-8"))

        kwargs["stderr"].write(serialize_trace(events).encode("utf-8"))

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
        )

    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=mismatched_process,
    ):
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert not result.evaluation.passed

    assert not get_check(
        result,
        "configuration_consistency",
    ).passed


@pytest.mark.parametrize(
    "stream",
    ["stdout", "stderr"],
)
def test_oversized_process_output(
    eval_settings,
    run_directory,
    stream,
):
    def oversized_process(command, **kwargs):
        successful_process(command, **kwargs)

        kwargs[stream].write(b"x" * (MAX_CAPTURE_BYTES + 1))

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
        )

    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=oversized_process,
    ):
        result = run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

    assert result.capture_truncated

    assert not result.evaluation.passed

    assert not get_check(
        result,
        "capture_size",
    ).passed


def test_case_artifacts_cannot_be_overwritten(
    eval_settings,
    run_directory,
):
    with patch(
        "agent.eval.runner.subprocess.run",
        side_effect=successful_process,
    ) as mocked:
        run_case(
            make_case(),
            eval_settings,
            run_directory,
        )

        with pytest.raises(FileExistsError):
            run_case(
                make_case(),
                eval_settings,
                run_directory,
            )

    assert mocked.call_count == 1


def test_all_cases_attempted_once(
    eval_settings,
    tmp_path,
):
    cases = []

    for index in range(3):
        case = make_case()

        case["id"] = f"synthetic-case-{index}"

        cases.append(case)

    outcomes = [
        subprocess.TimeoutExpired(
            cmd=["python", "-m", "agent"],
            timeout=330,
        ),
        OSError("Synthetic launch failure"),
        successful_process,
    ]

    attempted = []

    def mixed_process(command, **kwargs):
        outcome = outcomes[len(attempted)]

        attempted.append(command)

        if isinstance(outcome, BaseException):
            raise outcome

        return outcome(command, **kwargs)

    with (
        patch(
            "agent.eval.runner.load_cases",
            return_value=tuple(cases),
        ),
        patch(
            "agent.eval.runner.load_settings",
            return_value=eval_settings,
        ),
        patch(
            "agent.eval.runner.subprocess.run",
            side_effect=mixed_process,
        ) as mocked,
    ):
        run = run_evaluation(
            artifacts_root=tmp_path,
        )

    assert mocked.call_count == 3

    assert len(run.cases) == 3

    assert run.cases[0].timed_out

    assert run.cases[1].execution_error == ("process_launch_failed")

    assert run.cases[2].evaluation.passed

    assert sum(case.evaluation.passed for case in run.cases) == 1

    assert run.model == eval_settings.llm_model

    assert run.limits == LIMITS

    assert run.output_directory.is_dir()

    assert len(list((run.output_directory / "cases").iterdir())) == 6
