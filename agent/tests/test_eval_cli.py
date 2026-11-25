"""Regression tests for the evaluation command-line interface."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.config import ConfigurationError
from agent.eval import __main__ as cli
from agent.eval.runner import EvaluationRunnerError


def make_run(outcomes):
    """Construct a synthetic evaluation run."""

    return SimpleNamespace(
        cases=tuple(
            SimpleNamespace(
                evaluation=SimpleNamespace(
                    passed=passed,
                )
            )
            for passed in outcomes
        )
    )


@pytest.fixture
def mocked_evaluation():
    """Mock all live evaluation and reporting operations."""

    with (
        patch.object(cli, "run_evaluation") as runner,
        patch.object(cli, "write_reports") as writer,
        patch.object(cli, "render_console_summary") as renderer,
    ):
        runner.return_value = make_run([True])

        writer.return_value = (
            Path("results.json"),
            Path("report.md"),
        )

        renderer.return_value = "Synthetic evaluation summary"

        yield SimpleNamespace(
            runner=runner,
            writer=writer,
            renderer=renderer,
        )


def test_default_parser():
    parser = cli.build_parser()

    args = parser.parse_args([])

    assert not args.validate_only


def test_validation_parser():
    parser = cli.build_parser()

    args = parser.parse_args(["--validate-only"])

    assert args.validate_only


def test_help_does_not_execute_evaluation(
    mocked_evaluation,
    capsys,
):
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])

    assert error.value.code == 0

    output = capsys.readouterr()

    assert "--validate-only" in output.out
    assert not output.err

    mocked_evaluation.runner.assert_not_called()
    mocked_evaluation.writer.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--unknown"],
        ["unexpected"],
        ["--validate-only", "unexpected"],
    ],
)
def test_invalid_arguments(
    arguments,
    mocked_evaluation,
    capsys,
):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2

    output = capsys.readouterr()

    assert output.err

    mocked_evaluation.runner.assert_not_called()
    mocked_evaluation.writer.assert_not_called()


def test_dataset_validation(
    mocked_evaluation,
    capsys,
):
    exit_code = cli.main(["--validate-only"])

    output = capsys.readouterr()

    assert exit_code == 0

    assert "Valid evaluation cases: 6" in output.out

    assert "Dataset validation passed." in output.out

    assert "No investigations or LLM requests executed." in output.out

    assert not output.err

    mocked_evaluation.runner.assert_not_called()
    mocked_evaluation.writer.assert_not_called()
    mocked_evaluation.renderer.assert_not_called()


def test_dataset_validation_without_credentials(
    monkeypatch,
    mocked_evaluation,
    capsys,
):
    monkeypatch.delenv(
        "LLM_API_KEY",
        raising=False,
    )

    with patch(
        "agent.eval.runner.load_settings",
        side_effect=AssertionError("Validation must not load LLM settings."),
    ) as loader:
        exit_code = cli.main(["--validate-only"])

    assert exit_code == 0

    loader.assert_not_called()

    mocked_evaluation.runner.assert_not_called()

    output = capsys.readouterr()

    assert not output.err


def test_invalid_dataset(
    mocked_evaluation,
    capsys,
):
    with patch.object(
        cli,
        "load_cases",
        side_effect=EvaluationRunnerError("Synthetic invalid dataset."),
    ):
        exit_code = cli.main(["--validate-only"])

    assert exit_code == 2

    output = capsys.readouterr()

    assert output.err

    assert "Synthetic invalid dataset." not in output.err

    mocked_evaluation.runner.assert_not_called()
    mocked_evaluation.writer.assert_not_called()


@pytest.mark.parametrize(
    ("outcomes", "expected_code"),
    [
        ([True], 0),
        ([True, True], 0),
        ([True, False], 1),
        ([False, True], 1),
        ([False, False], 1),
        ([False], 1),
        ([], 1),
    ],
)
def test_evaluation_exit_codes(
    outcomes,
    expected_code,
    mocked_evaluation,
    capsys,
):
    run = make_run(outcomes)

    mocked_evaluation.runner.return_value = run

    exit_code = cli.main([])

    assert exit_code == expected_code

    mocked_evaluation.runner.assert_called_once_with()

    mocked_evaluation.writer.assert_called_once_with(run)

    mocked_evaluation.renderer.assert_called_once_with(run)

    output = capsys.readouterr()

    assert not output.err

    assert "Live LLM requests will be made." in output.out

    assert "Synthetic evaluation summary" in output.out

    assert "JSON report:" in output.out

    assert "Markdown report:" in output.out


def test_failed_evaluation_still_writes_reports(
    mocked_evaluation,
):
    run = make_run([False, False, False])

    mocked_evaluation.runner.return_value = run

    exit_code = cli.main([])

    assert exit_code == 1

    mocked_evaluation.writer.assert_called_once_with(run)


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (
            ConfigurationError("synthetic-sensitive-detail"),
            2,
        ),
        (
            EvaluationRunnerError("synthetic-sensitive-detail"),
            2,
        ),
        (
            OSError("synthetic-sensitive-detail"),
            3,
        ),
        (
            RuntimeError("synthetic-sensitive-detail"),
            3,
        ),
        (
            ValueError("synthetic-sensitive-detail"),
            3,
        ),
        (
            KeyboardInterrupt(),
            130,
        ),
    ],
)
def test_evaluation_error_handling(
    exception,
    expected_code,
    mocked_evaluation,
    capsys,
):
    mocked_evaluation.runner.side_effect = exception

    exit_code = cli.main([])

    assert exit_code == expected_code

    output = capsys.readouterr()

    assert output.err

    assert "synthetic-sensitive-detail" not in output.err

    assert "Traceback" not in output.err

    mocked_evaluation.writer.assert_not_called()

    mocked_evaluation.renderer.assert_not_called()


@pytest.mark.parametrize(
    "exception",
    [
        OSError("synthetic-sensitive-detail"),
        FileExistsError("synthetic-sensitive-detail"),
        RuntimeError("synthetic-sensitive-detail"),
    ],
)
def test_report_generation_failure(
    exception,
    mocked_evaluation,
    capsys,
):
    mocked_evaluation.writer.side_effect = exception

    exit_code = cli.main([])

    assert exit_code == 3

    mocked_evaluation.runner.assert_called_once_with()

    mocked_evaluation.writer.assert_called_once()

    mocked_evaluation.renderer.assert_not_called()

    output = capsys.readouterr()

    assert output.err

    assert "synthetic-sensitive-detail" not in output.err

    assert "Traceback" not in output.err


def test_interrupted_report_generation(
    mocked_evaluation,
    capsys,
):
    mocked_evaluation.writer.side_effect = KeyboardInterrupt()

    exit_code = cli.main([])

    assert exit_code == 130

    output = capsys.readouterr()

    assert "interrupted" in output.err.casefold()

    assert "Partial artifacts" in output.err


def test_console_rendering_failure(
    mocked_evaluation,
    capsys,
):
    mocked_evaluation.renderer.side_effect = RuntimeError("synthetic-sensitive-detail")

    exit_code = cli.main([])

    assert exit_code == 3

    mocked_evaluation.writer.assert_called_once()

    output = capsys.readouterr()

    assert output.err

    assert "synthetic-sensitive-detail" not in output.err


def test_reports_written_before_console_summary(
    mocked_evaluation,
):
    operations = []

    run = make_run([True])

    def execute():
        operations.append("run")

        return run

    def write(result):
        operations.append("write")

        assert result is run

        return (
            Path("results.json"),
            Path("report.md"),
        )

    def render(result):
        operations.append("render")

        assert result is run

        return "Synthetic summary"

    mocked_evaluation.runner.side_effect = execute

    mocked_evaluation.writer.side_effect = write

    mocked_evaluation.renderer.side_effect = render

    exit_code = cli.main([])

    assert exit_code == 0

    assert operations == [
        "run",
        "write",
        "render",
    ]
