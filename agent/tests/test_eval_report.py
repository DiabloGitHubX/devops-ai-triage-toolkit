"""Regression tests for evaluation reporting and aggregation."""

import json
from dataclasses import replace

import pytest

from agent.eval.evaluator import (
    EvaluationCheck,
    evaluate_case,
)
from agent.eval.report import (
    build_report_data,
    percentage,
    render_console_summary,
    render_markdown,
    summarize_run,
    write_reports,
)
from agent.eval.runner import (
    CaseExecution,
    EvaluationRun,
    create_run_directory,
)
from agent.tests.eval_helpers import (
    DIAGNOSIS,
    LIMITS,
    make_case,
    make_trace,
)


@pytest.fixture
def successful_evaluation():
    """Return a deterministic successful evaluation."""

    return evaluate_case(
        case=make_case(),
        diagnosis=DIAGNOSIS,
        stderr=make_trace(),
        exit_code=0,
    )


@pytest.fixture
def mixed_run(tmp_path, successful_evaluation):
    """Construct a run containing successful and failed cases."""

    run_id, directory = create_run_directory(tmp_path)

    successful = CaseExecution(
        case_id="ci-test-failure",
        category="ci",
        evaluation=successful_evaluation,
        wall_time_seconds=3.0,
        timed_out=False,
        capture_truncated=False,
        execution_error=None,
        diagnosis_path="cases/ci-test-failure.txt",
        trace_path="cases/ci-test-failure.trace.jsonl",
    )

    incomplete_evaluation = replace(
        successful_evaluation,
        case_id="k8s-image-pull",
        passed=False,
        completed=False,
        exit_code=1,
        stop_reason="llm_request_failed",
        total_tokens=1500,
        usage_complete=False,
        checks=(
            EvaluationCheck(
                name="investigation_completed",
                passed=False,
                detail="Synthetic incomplete investigation.",
            ),
            EvaluationCheck(
                name="token_accounting",
                passed=False,
                detail="Synthetic incomplete usage.",
            ),
        ),
    )

    incomplete = CaseExecution(
        case_id="k8s-image-pull",
        category="kubernetes",
        evaluation=incomplete_evaluation,
        wall_time_seconds=4.0,
        timed_out=False,
        capture_truncated=False,
        execution_error=None,
        diagnosis_path="cases/k8s-image-pull.txt",
        trace_path="cases/k8s-image-pull.trace.jsonl",
    )

    failed_evaluation = replace(
        successful_evaluation,
        case_id="ci-docker-build",
        passed=False,
        total_tokens=5000,
        checks=(
            EvaluationCheck(
                name="configuration_consistency",
                passed=False,
                detail="Synthetic configuration mismatch.",
            ),
        ),
    )

    completed_failure = CaseExecution(
        case_id="ci-docker-build",
        category="ci",
        evaluation=failed_evaluation,
        wall_time_seconds=5.0,
        timed_out=False,
        capture_truncated=False,
        execution_error=None,
        diagnosis_path="cases/ci-docker-build.txt",
        trace_path="cases/ci-docker-build.trace.jsonl",
    )

    return EvaluationRun(
        run_id=run_id,
        output_directory=directory,
        started_at="2026-01-01T12:00:00Z",
        finished_at="2026-01-01T12:00:12Z",
        model="synthetic-test-model",
        limits=LIMITS.copy(),
        cases=(
            successful,
            incomplete,
            completed_failure,
        ),
    )


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (0, 0, 0.0),
        (0, 3, 0.0),
        (1, 3, 33.33),
        (2, 3, 66.67),
        (3, 3, 100.0),
        (1, 2, 50.0),
        (1, 6, 16.67),
        (5, 6, 83.33),
    ],
)
def test_percentage(numerator, denominator, expected):
    assert percentage(numerator, denominator) == expected


def test_all_attempts_included(mixed_run):
    summary = summarize_run(mixed_run)

    assert summary["attempted"] == 3
    assert summary["passed"] == 1
    assert summary["failed"] == 2


def test_pass_and_completion_rates(mixed_run):
    summary = summarize_run(mixed_run)

    assert summary["completed"] == 2
    assert summary["incomplete"] == 1
    assert summary["pass_rate_percent"] == 33.33
    assert summary["completion_rate_percent"] == 66.67


def test_category_aggregation(mixed_run):
    categories = summarize_run(mixed_run)["categories"]

    assert categories["ci"]["attempted"] == 2
    assert categories["ci"]["passed"] == 1
    assert categories["ci"]["failed"] == 1
    assert categories["ci"]["pass_rate_percent"] == 50.0

    assert categories["kubernetes"]["attempted"] == 1
    assert categories["kubernetes"]["passed"] == 0
    assert categories["kubernetes"]["failed"] == 1
    assert categories["kubernetes"]["pass_rate_percent"] == 0.0


def test_failed_check_aggregation(mixed_run):
    summary = summarize_run(mixed_run)

    assert summary["failed_checks"] == {
        "configuration_consistency": 1,
        "investigation_completed": 1,
        "token_accounting": 1,
    }


def test_stop_reason_aggregation(mixed_run):
    summary = summarize_run(mixed_run)

    assert summary["stop_reasons"] == {
        "diagnosis_completed": 2,
        "llm_request_failed": 1,
    }


def test_token_accounting(mixed_run):
    summary = summarize_run(mixed_run)

    assert summary["usage_complete_cases"] == 2
    assert summary["usage_incomplete_cases"] == 1

    # Partial provider usage remains in the reported total.
    assert summary["reported_token_total"] == 10000

    # Only complete usage contributes to this total.
    assert summary["complete_usage_token_total"] == 8500

    assert summary["average_tokens_complete_usage"] == 4250.0


def test_wall_time_aggregation(mixed_run):
    summary = summarize_run(mixed_run)

    assert summary["total_wall_time_seconds"] == 12.0
    assert summary["average_wall_time_seconds"] == 4.0


def test_missing_token_usage_is_not_zero(mixed_run):
    original = mixed_run.cases[0]

    evaluation = replace(
        original.evaluation,
        total_tokens=None,
        usage_complete=False,
    )

    case = replace(
        original,
        evaluation=evaluation,
    )

    run = replace(
        mixed_run,
        cases=(case,),
    )

    summary = summarize_run(run)

    assert summary["reported_token_total"] is None
    assert summary["complete_usage_token_total"] is None
    assert summary["average_tokens_complete_usage"] is None
    assert summary["usage_complete_cases"] == 0
    assert summary["usage_incomplete_cases"] == 1


def test_partial_usage_without_complete_cases(mixed_run):
    run = replace(
        mixed_run,
        cases=(mixed_run.cases[1],),
    )

    summary = summarize_run(run)

    assert summary["reported_token_total"] == 1500
    assert summary["complete_usage_token_total"] is None
    assert summary["average_tokens_complete_usage"] is None


def test_timeout_and_execution_error_aggregation(mixed_run):
    timeout_case = replace(
        mixed_run.cases[1],
        timed_out=True,
        execution_error="process_timeout",
    )

    launch_failure = replace(
        mixed_run.cases[2],
        execution_error="process_launch_failed",
    )

    run = replace(
        mixed_run,
        cases=(
            mixed_run.cases[0],
            timeout_case,
            launch_failure,
        ),
    )

    summary = summarize_run(run)

    assert summary["timed_out"] == 1
    assert summary["execution_errors"] == 2
    assert summary["attempted"] == 3


def test_empty_run_summary(mixed_run):
    run = replace(
        mixed_run,
        cases=(),
    )

    summary = summarize_run(run)

    assert summary["attempted"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["pass_rate_percent"] == 0.0
    assert summary["completion_rate_percent"] == 0.0
    assert summary["reported_token_total"] is None
    assert summary["average_wall_time_seconds"] is None


def test_machine_readable_report_structure(mixed_run):
    report = build_report_data(mixed_run)

    assert report["schema_version"] == 1
    assert report["run_id"] == mixed_run.run_id
    assert report["model"] == mixed_run.model
    assert report["limits"] == LIMITS

    assert len(report["cases"]) == 3

    assert report["summary"] == summarize_run(mixed_run)

    assert report["cases"][0]["evaluation"]["passed"]

    assert not report["cases"][1]["evaluation"]["passed"]

    assert report["cases"][1]["evaluation"]["checks"]


def test_report_contains_no_credential_fields(mixed_run):
    report = build_report_data(mixed_run)

    serialized = json.dumps(report).casefold()

    assert "llm_api_key" not in serialized
    assert "synthetic-test-key" not in serialized
    assert "kubeconfig" not in serialized


def test_markdown_summary(mixed_run):
    markdown = render_markdown(mixed_run)

    assert mixed_run.run_id in markdown
    assert mixed_run.model in markdown
    assert "33.33%" in markdown
    assert "66.67%" in markdown


def test_markdown_case_artifact_links(mixed_run):
    markdown = render_markdown(mixed_run)

    for case in mixed_run.cases:
        assert f"({case.diagnosis_path})" in markdown
        assert f"({case.trace_path})" in markdown


def test_markdown_failure_details(mixed_run):
    markdown = render_markdown(mixed_run)

    assert "configuration_consistency" in markdown
    assert "llm_request_failed" in markdown
    assert "token_accounting" in markdown


def test_markdown_discloses_manual_review(mixed_run):
    markdown = render_markdown(mixed_run).casefold()

    assert "manual" in markdown
    assert "review" in markdown


def test_console_summary(mixed_run):
    console = render_console_summary(mixed_run)

    assert "[PASS] ci-test-failure" in console
    assert "[FAIL] k8s-image-pull" in console
    assert "[FAIL] ci-docker-build" in console

    assert "Automated passes: 1/3" in console
    assert "Automated pass rate: 33.33%" in console
    assert "Agent completion rate: 66.67%" in console
    assert "Reported tokens: 10000" in console
    assert "Complete usage accounting: 2/3" in console


def test_report_persistence(mixed_run):
    json_path, markdown_path = write_reports(mixed_run)

    assert json_path == (mixed_run.output_directory / "results.json")

    assert markdown_path == (mixed_run.output_directory / "report.md")

    assert json_path.is_file()
    assert markdown_path.is_file()

    stored_report = json.loads(json_path.read_text(encoding="utf-8"))

    expected_report = json.loads(json.dumps(build_report_data(mixed_run)))

    assert stored_report == expected_report

    assert markdown_path.read_text(encoding="utf-8") == render_markdown(mixed_run)


def test_existing_reports_cannot_be_overwritten(mixed_run):
    json_path, markdown_path = write_reports(mixed_run)

    original_json = json_path.read_bytes()
    original_markdown = markdown_path.read_bytes()

    with pytest.raises(FileExistsError):
        write_reports(mixed_run)

    assert json_path.read_bytes() == original_json
    assert markdown_path.read_bytes() == original_markdown


@pytest.mark.parametrize(
    "filename",
    ["results.json", "report.md"],
)
def test_existing_partial_report_is_preserved(
    mixed_run,
    filename,
):
    existing = mixed_run.output_directory / filename

    existing.write_text(
        "Existing report content.",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError):
        write_reports(mixed_run)

    assert existing.read_text(encoding="utf-8") == "Existing report content."
