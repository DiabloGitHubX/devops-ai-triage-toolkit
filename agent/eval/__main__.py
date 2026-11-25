"""Command-line entry point for the diagnostic agent evaluation."""

import argparse
import sys

from agent.config import ConfigurationError
from agent.eval.report import (
    render_console_summary,
    write_reports,
)
from agent.eval.runner import (
    EvaluationRunnerError,
    load_cases,
    run_evaluation,
)

EXIT_SUCCESS = 0

EXIT_EVALUATION_FAILED = 1

EXIT_CONFIGURATION_ERROR = 2

EXIT_RUNTIME_ERROR = 3

EXIT_INTERRUPTED = 130


def configure_output_encoding() -> None:
    """Ensure readable output on Windows and Unix terminals."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(
            stream,
            "reconfigure",
            None,
        )

        if callable(reconfigure):
            reconfigure(
                encoding="utf-8",
                errors="backslashreplace",
            )


def build_parser() -> argparse.ArgumentParser:
    """Define the evaluation command-line interface."""

    parser = argparse.ArgumentParser(
        prog="python -m agent.eval",
        description=(
            "Evaluate the DevOps AI triage agent against "
            "the configured Kubernetes and CI failure cases."
        ),
        epilog=(
            "Each case is attempted once. "
            "Reports include failed investigations. "
            "Automated results require manual review."
        ),
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Validate and list evaluation cases without "
            "executing the agent or contacting an LLM."
        ),
    )

    return parser


def validate_dataset() -> int:
    """Validate the dataset without loading LLM credentials."""

    cases = load_cases()

    print("Evaluation dataset validation")
    print("=" * 40)

    for case in cases:
        print(f"- {case['id']} ({case['category']})")

    print()
    print(f"Valid evaluation cases: {len(cases)}")
    print("Dataset validation passed.")
    print("No investigations or LLM requests executed.")

    return EXIT_SUCCESS


def execute_evaluation() -> int:
    """Execute the full evaluation and persist its reports."""

    print(
        "Starting DevOps AI triage evaluation.",
        flush=True,
    )

    print(
        "Each configured case will be attempted once.",
        flush=True,
    )

    print(
        "Live LLM requests will be made.",
        flush=True,
    )

    run = run_evaluation()

    json_path, markdown_path = write_reports(run)

    print(render_console_summary(run))

    print()
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")

    if run.cases and all(case.evaluation.passed for case in run.cases):
        return EXIT_SUCCESS

    return EXIT_EVALUATION_FAILED


def main(
    argv: list[str] | None = None,
) -> int:
    """Run the requested evaluation command."""

    configure_output_encoding()

    parser = build_parser()

    args = parser.parse_args(argv)

    try:
        if args.validate_only:
            return validate_dataset()

        return execute_evaluation()

    except (
        ConfigurationError,
        EvaluationRunnerError,
    ):
        print(
            "Evaluation configuration or dataset is invalid. "
            "Check the documented settings and cases.json.",
            file=sys.stderr,
        )

        return EXIT_CONFIGURATION_ERROR

    except KeyboardInterrupt:
        print(
            "Evaluation interrupted. Partial artifacts may remain.",
            file=sys.stderr,
        )

        return EXIT_INTERRUPTED

    except Exception:  # noqa: BLE001
        # Avoid exposing credentials or internal provider
        # details through unexpected exception messages.
        print(
            "Evaluation infrastructure or report generation "
            "failed. Inspect the local evaluation artifacts.",
            file=sys.stderr,
        )

        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
