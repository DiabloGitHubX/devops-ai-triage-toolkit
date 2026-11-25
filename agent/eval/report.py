"""Generate machine-readable and human-readable evaluation reports.

All attempted cases contribute to the reported pass rate.
Automated evaluation is heuristic and does not replace manual review.
"""

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent.eval.runner import EvaluationRun

REPORT_SCHEMA_VERSION = 1


def percentage(
    numerator: int,
    denominator: int,
) -> float:
    """Calculate a percentage without division-by-zero errors."""

    if denominator == 0:
        return 0.0

    return round(
        numerator / denominator * 100,
        2,
    )


def summarize_run(
    run: EvaluationRun,
) -> dict[str, Any]:
    """Calculate aggregate metrics from every attempted case."""

    total = len(run.cases)

    passed = sum(case.evaluation.passed for case in run.cases)

    completed = sum(case.evaluation.completed for case in run.cases)

    timed_out = sum(case.timed_out for case in run.cases)

    execution_errors = sum(case.execution_error is not None for case in run.cases)

    complete_usage_cases = [
        case
        for case in run.cases
        if case.evaluation.usage_complete and case.evaluation.total_tokens is not None
    ]

    reported_token_values = [
        case.evaluation.total_tokens
        for case in run.cases
        if case.evaluation.total_tokens is not None
    ]

    complete_token_values = [
        case.evaluation.total_tokens
        for case in complete_usage_cases
        if case.evaluation.total_tokens is not None
    ]

    total_wall_time = sum(case.wall_time_seconds for case in run.cases)

    failed_checks = Counter(
        check.name
        for case in run.cases
        for check in case.evaluation.checks
        if not check.passed
    )

    stop_reasons = Counter(case.evaluation.stop_reason for case in run.cases)

    categories: dict[str, dict[str, Any]] = {}

    for category in sorted({case.category for case in run.cases}):
        category_cases = [case for case in run.cases if case.category == category]

        category_total = len(category_cases)

        category_passed = sum(case.evaluation.passed for case in category_cases)

        categories[category] = {
            "attempted": category_total,
            "passed": category_passed,
            "failed": category_total - category_passed,
            "pass_rate_percent": percentage(
                category_passed,
                category_total,
            ),
        }

    return {
        "attempted": total,
        "passed": passed,
        "failed": total - passed,
        "completed": completed,
        "incomplete": total - completed,
        "pass_rate_percent": percentage(
            passed,
            total,
        ),
        "completion_rate_percent": percentage(
            completed,
            total,
        ),
        "timed_out": timed_out,
        "execution_errors": execution_errors,
        "usage_complete_cases": len(complete_usage_cases),
        "usage_incomplete_cases": (total - len(complete_usage_cases)),
        "reported_token_total": (
            sum(reported_token_values) if reported_token_values else None
        ),
        "complete_usage_token_total": (
            sum(complete_token_values) if complete_token_values else None
        ),
        "average_tokens_complete_usage": (
            round(
                sum(complete_token_values) / len(complete_token_values),
                2,
            )
            if complete_token_values
            else None
        ),
        "total_wall_time_seconds": round(
            total_wall_time,
            3,
        ),
        "average_wall_time_seconds": (
            round(total_wall_time / total, 3) if total else None
        ),
        "failed_checks": dict(sorted(failed_checks.items())),
        "stop_reasons": dict(sorted(stop_reasons.items())),
        "categories": categories,
    }


def build_report_data(
    run: EvaluationRun,
) -> dict[str, Any]:
    """Build the versioned JSON report without credentials."""

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run.run_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "model": run.model,
        "limits": dict(run.limits),
        "evaluation_method": (
            "Deterministic heuristic scoring; "
            "one attempt per configured case; "
            "manual review required."
        ),
        "summary": summarize_run(run),
        "cases": [asdict(case) for case in run.cases],
    }


def display_value(value: Any) -> str:
    """Render unavailable values explicitly."""

    if value is None:
        return "N/A"

    if isinstance(value, bool):
        return "Yes" if value else "No"

    return str(value)


def markdown_cell(value: Any) -> str:
    """Keep table values on one line and escape separators."""

    text = display_value(value)

    text = " ".join(text.split())

    return text.replace("|", r"\|")


def render_markdown(
    run: EvaluationRun,
) -> str:
    """Render a standalone Markdown evaluation report."""

    summary = summarize_run(run)

    lines = [
        "# DevOps AI Triage — Evaluation Report",
        "",
        f"- Run ID: `{run.run_id}`",
        f"- Started: {run.started_at}",
        f"- Finished: {run.finished_at}",
        f"- Model: `{run.model}`",
        "- Execution policy: one attempt per case, no retries.",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Attempted cases | {summary['attempted']} |",
        f"| Passed cases | {summary['passed']} |",
        f"| Failed cases | {summary['failed']} |",
        f"| Completed investigations | {summary['completed']} |",
        f"| Incomplete investigations | {summary['incomplete']} |",
        (f"| Automated pass rate | {summary['pass_rate_percent']:.2f}% |"),
        (f"| Agent completion rate | {summary['completion_rate_percent']:.2f}% |"),
        f"| Process timeouts | {summary['timed_out']} |",
        (f"| Subprocess execution errors | {summary['execution_errors']} |"),
        (f"| Total subprocess wall time | {summary['total_wall_time_seconds']:.3f}s |"),
        "",
        "All attempted cases contribute to the pass-rate denominator.",
        "A completed investigation is not necessarily a passing investigation.",
        "",
        "## Execution configuration",
        "",
        "| Limit | Value |",
        "|---|---:|",
    ]

    for name, value in sorted(run.limits.items()):
        lines.append(f"| {markdown_cell(name)} | {value} |")

    lines.extend(
        [
            "",
            "## Results by category",
            "",
            "| Category | Attempted | Passed | Failed | Pass rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )

    for category, metrics in summary["categories"].items():
        lines.append(
            f"| {markdown_cell(category)} "
            f"| {metrics['attempted']} "
            f"| {metrics['passed']} "
            f"| {metrics['failed']} "
            f"| {metrics['pass_rate_percent']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Individual case results",
            "",
            (
                "| Case | Outcome | Completed | Exit code "
                "| Tools | LLM calls | Reported tokens "
                "| Usage complete | Wall time |"
            ),
            "|---|---|---|---:|---:|---:|---:|---|---:|",
        ]
    )

    for case in run.cases:
        result = case.evaluation

        outcome = "PASS" if result.passed else "FAIL"

        values = [
            case.case_id,
            outcome,
            result.completed,
            result.exit_code,
            result.tool_attempts,
            result.llm_calls,
            result.total_tokens,
            result.usage_complete,
            f"{case.wall_time_seconds:.3f}s",
        ]

        lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")

    lines.extend(
        [
            "",
            "## Token usage",
            "",
            "| Metric | Value |",
            "|---|---:|",
            (
                "| Cases with complete usage accounting | "
                f"{summary['usage_complete_cases']} |"
            ),
            (
                "| Cases with incomplete usage accounting | "
                f"{summary['usage_incomplete_cases']} |"
            ),
            (
                "| Sum of reported tokens | "
                f"{display_value(summary['reported_token_total'])} |"
            ),
            (
                "| Tokens from complete-usage cases | "
                f"{display_value(summary['complete_usage_token_total'])} |"
            ),
            (
                "| Average tokens per complete-usage case | "
                f"{display_value(summary['average_tokens_complete_usage'])} |"
            ),
            "",
            "Reported tokens may omit usage from failed provider requests.",
            "When usage is incomplete, the reported total is not a verified",
            "total consumption or billing figure.",
            "",
            "## Stop reasons",
            "",
            "| Reason | Cases |",
            "|---|---:|",
        ]
    )

    for reason, count in summary["stop_reasons"].items():
        lines.append(f"| {markdown_cell(reason)} | {count} |")

    lines.extend(
        [
            "",
            "## Failed evaluation checks",
            "",
        ]
    )

    if summary["failed_checks"]:
        lines.extend(
            [
                "| Check | Failures |",
                "|---|---:|",
            ]
        )

        for name, count in sorted(
            summary["failed_checks"].items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| {markdown_cell(name)} | {count} |")
    else:
        lines.append("No automated evaluation checks failed.")

    lines.extend(
        [
            "",
            "## Detailed case results",
        ]
    )

    for case in run.cases:
        result = case.evaluation

        outcome = "PASS" if result.passed else "FAIL"

        lines.extend(
            [
                "",
                f"### {case.case_id} — {outcome}",
                "",
                (f"- Stop reason: {markdown_cell(result.stop_reason)}"),
                (f"- Execution error: {markdown_cell(case.execution_error)}"),
                (f"- Process timed out: {display_value(case.timed_out)}"),
                (f"- Capture truncated: {display_value(case.capture_truncated)}"),
                (
                    "- Successful tools: "
                    + (", ".join(result.successful_tools) or "None")
                ),
                (f"- [Diagnosis]({case.diagnosis_path})"),
                (f"- [Trace]({case.trace_path})"),
                "",
                "| Check | Outcome | Detail |",
                "|---|---|---|",
            ]
        )

        for check in result.checks:
            status = "PASS" if check.passed else "FAIL"

            lines.append(
                f"| {markdown_cell(check.name)} "
                f"| {status} "
                f"| {markdown_cell(check.detail)} |"
            )

    lines.extend(
        [
            "",
            "## Evaluation limitations",
            "",
            "- Automated root-cause and evidence matching is heuristic.",
            "- Keyword matches do not establish semantic correctness.",
            "- Trace checks validate observable execution records,",
            "  not independently authenticated execution.",
            "- Suggested fixes require manual technical review.",
            "- The dataset contains controlled synthetic failures.",
            "- Results do not establish production-wide reliability.",
            "- Provider behavior and live Kubernetes events may vary.",
            "- Reported token usage is not a verified billing total.",
            "",
            "## Manual review",
            "",
            "Manual review is required before interpreting the automated",
            "pass rate as a measure of diagnostic quality.",
            "",
            "Review root-cause correctness, evidence fidelity,",
            "remediation accuracy and adherence to read-only behavior.",
            "",
        ]
    )

    return "\n".join(lines)


def render_console_summary(
    run: EvaluationRun,
) -> str:
    """Render a compact terminal summary."""

    summary = summarize_run(run)

    lines = [
        "",
        "=" * 64,
        "DEVOPS AI TRIAGE — EVALUATION SUMMARY",
        "=" * 64,
        f"Run ID: {run.run_id}",
        f"Model: {run.model}",
        "",
    ]

    for case in run.cases:
        result = case.evaluation

        outcome = "PASS" if result.passed else "FAIL"

        lines.append(f"[{outcome}] {case.case_id} ({case.wall_time_seconds:.3f}s)")

        if not result.passed:
            failed = [check.name for check in result.checks if not check.passed]

            lines.append(f"       Stop reason: {result.stop_reason}")

            lines.append("       Failed checks: " + ", ".join(failed))

    lines.extend(
        [
            "",
            (f"Automated passes: {summary['passed']}/{summary['attempted']}"),
            (f"Automated pass rate: {summary['pass_rate_percent']:.2f}%"),
            (f"Agent completion rate: {summary['completion_rate_percent']:.2f}%"),
            (f"Reported tokens: {display_value(summary['reported_token_total'])}"),
            (
                "Complete usage accounting: "
                f"{summary['usage_complete_cases']}/"
                f"{summary['attempted']}"
            ),
            (f"Total subprocess wall time: {summary['total_wall_time_seconds']:.3f}s"),
            "",
            f"Artifacts: {run.output_directory}",
            "Manual diagnosis review required.",
            "=" * 64,
        ]
    )

    return "\n".join(lines)


def write_reports(
    run: EvaluationRun,
) -> tuple[Path, Path]:
    """Write reports without replacing an existing report."""

    json_path = run.output_directory / "results.json"

    markdown_path = run.output_directory / "report.md"

    if json_path.exists() or markdown_path.exists():
        raise FileExistsError("Evaluation reports already exist.")

    json_content = json.dumps(
        build_report_data(run),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )

    markdown_content = render_markdown(run)

    with json_path.open(
        "x",
        encoding="utf-8",
        newline="\n",
    ) as file:
        file.write(json_content + "\n")

    with markdown_path.open(
        "x",
        encoding="utf-8",
        newline="\n",
    ) as file:
        file.write(markdown_content)

    return json_path, markdown_path
