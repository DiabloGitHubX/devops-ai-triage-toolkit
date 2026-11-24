"""Regression tests for the diagnostic agent CLI."""

import asyncio
import io
import runpy
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent import cli
from agent.agent_loop import MAX_QUERY_BYTES
from agent.config import ConfigurationError
from agent.llm_client import LLMClientError
from agent.mcp_client import MCPClientError

DIAGNOSIS = """### Symptom
CI test failure.

### Evidence
assert 201 == 400

### Root cause
Negative payment amounts are accepted.

### Suggested fix
Validate the payment amount before processing.

### Confidence
High.
"""


@pytest.mark.parametrize(
    "argv",
    [
        ["--ci", "build-1423"],
        ["--ci", "Build_1423"],
        ["--pod", "payments-api"],
        ["--pod", "orders-api-7dbf8655c5-2s9sb"],
        ["--pod", "analytics-worker", "--namespace", "staging"],
        ["Investigate unhealthy pods"],
        ["--namespace", "staging", "Investigate unhealthy pods"],
    ],
)
def test_accept_valid_arguments(argv):
    args = cli.parse_arguments(argv)

    assert sum(value is not None for value in (args.ci, args.pod, args.query)) == 1


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--namespace", "staging"],
        ["--ci", "build-1423", "--pod", "payments-api"],
        ["--ci", "build-1423", "Investigate pods"],
        ["--pod", "payments-api", "Investigate CI"],
        ["--ci", "build-1423", "--namespace", "staging"],
        ["--ci"],
        ["--pod"],
        ["--namespace"],
        ["--unknown"],
        ["--na", "staging", "--pod", "payments-api"],
        ["--p", "payments-api"],
        [""],
        ["   "],
        ["\t\n"],
        ["Investigate", "pods"],
    ],
)
def test_reject_invalid_argument_combinations(argv, capsys):
    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments(argv)

    assert captured.value.code == cli.EXIT_USAGE_ERROR
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "namespace",
    [
        "staging",
        "production",
        "dev-01",
        "a",
        "0",
        "a" * 63,
    ],
)
def test_accept_valid_namespace(namespace):
    args = cli.parse_arguments(["--pod", "payments-api", "--namespace", namespace])

    assert args.namespace == namespace


@pytest.mark.parametrize(
    "namespace",
    [
        "",
        "Staging",
        "STAGING",
        "../staging",
        "staging/prod",
        "staging.prod",
        "staging_prod",
        "-staging",
        "staging-",
        "staging prod",
        "a" * 64,
    ],
)
def test_reject_invalid_namespace(namespace):
    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments(
            [
                "--pod",
                "payments-api",
                f"--namespace={namespace}",
            ]
        )

    assert captured.value.code == cli.EXIT_USAGE_ERROR


@pytest.mark.parametrize(
    "pod_name",
    [
        "payments-api",
        "orders-api-7dbf8655c5-2s9sb",
        "worker.01",
        "a",
        "0",
        "a" * 253,
    ],
)
def test_accept_valid_pod_name(pod_name):
    args = cli.parse_arguments(["--pod", pod_name])

    assert args.pod == pod_name


@pytest.mark.parametrize(
    "pod_name",
    [
        "",
        "Payments-api",
        "../payments-api",
        "payments/api",
        "payments_api",
        "-payments",
        "payments-",
        ".payments",
        "payments.",
        "payments..api",
        "payments api",
        "a" * 254,
    ],
)
def test_reject_invalid_pod_name(pod_name):
    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments([f"--pod={pod_name}"])

    assert captured.value.code == cli.EXIT_USAGE_ERROR


@pytest.mark.parametrize(
    "job_id",
    [
        "build-1423",
        "Build_1423",
        "job123",
        "1",
        "a" * 128,
    ],
)
def test_accept_valid_ci_job_id(job_id):
    args = cli.parse_arguments(["--ci", job_id])

    assert args.ci == job_id


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        "../build-1423",
        "fixtures/ci/build-1423",
        "build-1423.log",
        "/build-1423",
        "C:\\build-1423",
        "build 1423",
        "_build",
        "-build",
        "a" * 129,
    ],
)
def test_reject_invalid_ci_job_id(job_id):
    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments([f"--ci={job_id}"])

    assert captured.value.code == cli.EXIT_USAGE_ERROR


def test_query_whitespace_is_removed():
    args = cli.parse_arguments(["  Investigate payments-api  "])

    assert args.query == "Investigate payments-api"


def test_accept_query_at_size_limit():
    query = "x" * MAX_QUERY_BYTES

    args = cli.parse_arguments([query])

    assert args.query == query


def test_reject_query_above_size_limit():
    query = "x" * (MAX_QUERY_BYTES + 1)

    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments([query])

    assert captured.value.code == cli.EXIT_USAGE_ERROR


def test_query_size_counts_utf8_bytes():
    query = "\u2603" * MAX_QUERY_BYTES

    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments([query])

    assert captured.value.code == cli.EXIT_USAGE_ERROR


def test_help_output(capsys):
    with pytest.raises(SystemExit) as captured:
        cli.parse_arguments(["--help"])

    assert captured.value.code == 0

    output = capsys.readouterr()

    assert "--ci" in output.out
    assert "--pod" in output.out
    assert "--namespace" in output.out
    assert "never executes" in output.out
    assert output.err == ""


def test_build_ci_query():
    args = cli.parse_arguments(["--ci", "build-1423"])

    query = cli.build_query(args, "staging")

    assert "failed CI job build-1423" in query
    assert "root cause" in query
    assert "Do not execute remediation." in query


def test_build_pod_query_with_default_namespace():
    args = cli.parse_arguments(["--pod", "payments-api"])

    query = cli.build_query(args, "staging")

    assert "payments-api in namespace staging" in query
    assert "Discover the exact pod name" in query
    assert "Do not execute remediation." in query


def test_build_pod_query_with_explicit_namespace():
    args = cli.parse_arguments(
        [
            "--pod",
            "payments-api",
            "--namespace",
            "custom",
        ]
    )

    query = cli.build_query(args, "staging")

    assert "payments-api in namespace custom" in query
    assert "namespace staging" not in query


def test_build_natural_language_query():
    original = "Why is payments-api unhealthy?"

    args = cli.parse_arguments([original])

    assert cli.build_query(args, "staging") == original


def test_build_natural_language_query_with_namespace():
    args = cli.parse_arguments(
        [
            "--namespace",
            "custom",
            "Investigate unhealthy pods",
        ]
    )

    query = cli.build_query(args, "staging")

    assert query == (
        "Requested Kubernetes namespace: custom.\nInvestigate unhealthy pods"
    )


@pytest.fixture
def runtime(monkeypatch, settings):
    """Isolate CLI execution from configuration and network access."""

    load_settings = MagicMock(return_value=settings)

    load_skill = MagicMock(return_value="Synthetic triage Skill.")

    configure_trace = MagicMock()

    investigate = AsyncMock(
        return_value=SimpleNamespace(
            diagnosis=DIAGNOSIS,
            completed=True,
        )
    )

    monkeypatch.setattr(
        cli,
        "load_settings",
        load_settings,
    )

    monkeypatch.setattr(
        cli,
        "load_skill",
        load_skill,
    )

    monkeypatch.setattr(
        cli,
        "configure_trace_logging",
        configure_trace,
    )

    monkeypatch.setattr(
        cli,
        "run_investigation",
        investigate,
    )

    return SimpleNamespace(
        load_settings=load_settings,
        load_skill=load_skill,
        configure_trace=configure_trace,
        investigate=investigate,
    )


def test_main_success(runtime, settings, capsys):
    exit_code = cli.main(["--ci", "build-1423"])

    assert exit_code == cli.EXIT_SUCCESS

    output = capsys.readouterr()

    assert output.out.strip() == DIAGNOSIS.strip()
    assert output.err == ""

    runtime.load_settings.assert_called_once_with()

    runtime.load_skill.assert_called_once_with(settings.skill_path)

    runtime.configure_trace.assert_called_once_with()

    runtime.investigate.assert_awaited_once_with(
        settings,
        "Synthetic triage Skill.",
        cli.build_query(
            cli.parse_arguments(["--ci", "build-1423"]),
            settings.default_namespace,
        ),
    )


def test_main_incomplete_investigation(runtime, capsys):
    runtime.investigate.return_value = SimpleNamespace(
        diagnosis="Unknown — insufficient evidence.",
        completed=False,
    )

    exit_code = cli.main(["--pod", "payments-api"])

    assert exit_code == cli.EXIT_INCOMPLETE

    output = capsys.readouterr()

    assert "Unknown" in output.out
    assert output.err == ""


def test_main_invalid_arguments_skip_initialization(
    runtime,
    capsys,
):
    with pytest.raises(SystemExit) as captured:
        cli.main([])

    assert captured.value.code == cli.EXIT_USAGE_ERROR

    runtime.load_settings.assert_not_called()
    runtime.load_skill.assert_not_called()
    runtime.configure_trace.assert_not_called()
    runtime.investigate.assert_not_awaited()

    assert "error:" in capsys.readouterr().err


def test_main_help_skips_initialization(
    runtime,
    capsys,
):
    with pytest.raises(SystemExit) as captured:
        cli.main(["--help"])

    assert captured.value.code == 0

    runtime.load_settings.assert_not_called()
    runtime.investigate.assert_not_awaited()

    assert "--ci" in capsys.readouterr().out


def test_main_configuration_error(runtime, capsys):
    runtime.load_settings.side_effect = ConfigurationError(
        "synthetic-private-credential"
    )

    exit_code = cli.main(["--ci", "build-1423"])

    assert exit_code == cli.EXIT_USAGE_ERROR

    output = capsys.readouterr()

    assert output.out == ""
    assert "Invalid agent configuration or Skill" in output.err
    assert "synthetic-private-credential" not in output.err

    runtime.load_skill.assert_not_called()
    runtime.investigate.assert_not_awaited()


def test_main_skill_error(runtime, capsys):
    runtime.load_skill.side_effect = ConfigurationError(
        "synthetic-private-skill-content"
    )

    exit_code = cli.main(["--ci", "build-1423"])

    assert exit_code == cli.EXIT_USAGE_ERROR

    output = capsys.readouterr()

    assert output.out == ""
    assert "Invalid agent configuration or Skill" in output.err
    assert "synthetic-private-skill-content" not in output.err

    runtime.configure_trace.assert_not_called()
    runtime.investigate.assert_not_awaited()


def test_main_generated_query_size_limit(runtime, capsys):
    query = "x" * MAX_QUERY_BYTES

    exit_code = cli.main(["--namespace", "staging", query])

    assert exit_code == cli.EXIT_USAGE_ERROR

    output = capsys.readouterr()

    assert output.out == ""
    assert "Generated investigation query exceeds" in output.err

    runtime.configure_trace.assert_not_called()
    runtime.investigate.assert_not_awaited()


@pytest.mark.parametrize(
    ("exception_type", "expected"),
    [
        (
            MCPClientError,
            "Unable to initialize or use the MCP",
        ),
        (
            LLMClientError,
            "Unable to initialize or use the configured LLM",
        ),
        (
            RuntimeError,
            "Investigation failed unexpectedly",
        ),
        (
            OSError,
            "Investigation failed unexpectedly",
        ),
        (
            ValueError,
            "Investigation failed unexpectedly",
        ),
    ],
)
def test_main_runtime_errors_are_sanitized(
    runtime,
    capsys,
    exception_type,
    expected,
):
    runtime.investigate.side_effect = exception_type("synthetic-private-credential")

    exit_code = cli.main(["--ci", "build-1423"])

    assert exit_code == cli.EXIT_RUNTIME_ERROR

    output = capsys.readouterr()

    assert output.out == ""
    assert expected in output.err
    assert "synthetic-private-credential" not in output.err
    assert "Traceback" not in output.err


def test_main_keyboard_interrupt(runtime, capsys):
    runtime.load_settings.side_effect = KeyboardInterrupt()

    exit_code = cli.main(["--ci", "build-1423"])

    assert exit_code == cli.EXIT_INTERRUPTED

    output = capsys.readouterr()

    assert output.out == ""
    assert "Investigation interrupted." in output.err

    runtime.investigate.assert_not_awaited()


def test_main_uses_configured_default_namespace(
    runtime,
    settings,
):
    custom_settings = replace(
        settings,
        default_namespace="custom",
    )

    runtime.load_settings.return_value = custom_settings

    exit_code = cli.main(["--pod", "payments-api"])

    assert exit_code == cli.EXIT_SUCCESS

    arguments = runtime.investigate.await_args.args

    assert arguments[0] is custom_settings
    assert "namespace custom" in arguments[2]


@pytest.fixture
def lifecycle(monkeypatch, settings):
    """Mock client context managers and the diagnostic agent."""

    events = []

    mcp = MagicMock()
    llm = MagicMock()

    result = SimpleNamespace(
        diagnosis=DIAGNOSIS,
        completed=True,
    )

    agent = MagicMock()

    async def investigate(query):
        events.append("investigate")

        return result

    agent.investigate = AsyncMock(side_effect=investigate)

    agent_constructor = MagicMock(return_value=agent)

    @asynccontextmanager
    async def fake_mcp(*, timeout_seconds):
        assert timeout_seconds == settings.mcp_timeout

        events.append("mcp_enter")

        try:
            yield mcp

        finally:
            events.append("mcp_exit")

    @asynccontextmanager
    async def fake_llm(received_settings):
        assert received_settings is settings

        events.append("llm_enter")

        try:
            yield llm

        finally:
            events.append("llm_exit")

    monkeypatch.setattr(
        cli,
        "connect_mcp",
        fake_mcp,
    )

    monkeypatch.setattr(
        cli,
        "DiagnosticLLMClient",
        fake_llm,
    )

    monkeypatch.setattr(
        cli,
        "DiagnosticAgent",
        agent_constructor,
    )

    return SimpleNamespace(
        events=events,
        mcp=mcp,
        llm=llm,
        agent=agent,
        constructor=agent_constructor,
        result=result,
    )


def test_run_investigation_lifecycle(
    lifecycle,
    settings,
):
    query = "Investigate payments-api."
    skill = "Synthetic triage Skill."

    result = asyncio.run(
        cli.run_investigation(
            settings,
            skill,
            query,
        )
    )

    assert result is lifecycle.result

    assert lifecycle.events == [
        "mcp_enter",
        "llm_enter",
        "investigate",
        "llm_exit",
        "mcp_exit",
    ]

    lifecycle.constructor.assert_called_once_with(
        settings=settings,
        skill=skill,
        llm=lifecycle.llm,
        mcp=lifecycle.mcp,
    )

    lifecycle.agent.investigate.assert_awaited_once_with(query)


def test_investigation_failure_closes_clients(
    lifecycle,
    settings,
):
    lifecycle.agent.investigate.side_effect = RuntimeError(
        "Synthetic investigation failure"
    )

    with pytest.raises(
        RuntimeError,
        match="Synthetic investigation failure",
    ):
        asyncio.run(
            cli.run_investigation(
                settings,
                "Synthetic Skill.",
                "Investigate payments-api.",
            )
        )

    assert lifecycle.events == [
        "mcp_enter",
        "llm_enter",
        "llm_exit",
        "mcp_exit",
    ]


def test_agent_initialization_failure_closes_clients(
    lifecycle,
    settings,
):
    lifecycle.constructor.side_effect = RuntimeError(
        "Synthetic agent initialization failure"
    )

    with pytest.raises(
        RuntimeError,
        match="Synthetic agent initialization failure",
    ):
        asyncio.run(
            cli.run_investigation(
                settings,
                "Synthetic Skill.",
                "Investigate payments-api.",
            )
        )

    assert lifecycle.events == [
        "mcp_enter",
        "llm_enter",
        "llm_exit",
        "mcp_exit",
    ]

    lifecycle.agent.investigate.assert_not_awaited()


def test_llm_initialization_failure_closes_mcp(
    monkeypatch,
    lifecycle,
    settings,
):
    @asynccontextmanager
    async def failing_llm(received_settings):
        assert received_settings is settings

        lifecycle.events.append("llm_enter")

        raise LLMClientError("Synthetic LLM initialization failure")

        yield  # pragma: no cover

    monkeypatch.setattr(
        cli,
        "DiagnosticLLMClient",
        failing_llm,
    )

    with pytest.raises(
        LLMClientError,
        match="Synthetic LLM initialization failure",
    ):
        asyncio.run(
            cli.run_investigation(
                settings,
                "Synthetic Skill.",
                "Investigate payments-api.",
            )
        )

    assert lifecycle.events == [
        "mcp_enter",
        "llm_enter",
        "mcp_exit",
    ]

    lifecycle.constructor.assert_not_called()


def test_mcp_initialization_failure_skips_llm(
    monkeypatch,
    lifecycle,
    settings,
):
    @asynccontextmanager
    async def failing_mcp(*, timeout_seconds):
        assert timeout_seconds == settings.mcp_timeout

        lifecycle.events.append("mcp_enter")

        raise MCPClientError("Synthetic MCP initialization failure")

        yield  # pragma: no cover

    monkeypatch.setattr(
        cli,
        "connect_mcp",
        failing_mcp,
    )

    with pytest.raises(
        MCPClientError,
        match="Synthetic MCP initialization failure",
    ):
        asyncio.run(
            cli.run_investigation(
                settings,
                "Synthetic Skill.",
                "Investigate payments-api.",
            )
        )

    assert lifecycle.events == ["mcp_enter"]

    lifecycle.constructor.assert_not_called()


@pytest.mark.parametrize(
    "exit_code",
    [0, 1, 2, 3, 130],
)
def test_package_entry_point_propagates_exit_code(
    monkeypatch,
    exit_code,
):
    main = MagicMock(return_value=exit_code)

    monkeypatch.setattr(
        cli,
        "main",
        main,
    )

    with pytest.raises(SystemExit) as captured:
        runpy.run_module(
            "agent.__main__",
            run_name="__main__",
        )

    assert captured.value.code == exit_code

    main.assert_called_once_with()


def test_configure_output_encoding_reconfigures_both_streams(
    monkeypatch,
):
    stdout = MagicMock()
    stderr = MagicMock()

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", stdout)
        patch.setattr(sys, "stderr", stderr)

        cli.configure_output_encoding()

    stdout.reconfigure.assert_called_once_with(
        encoding="utf-8",
        errors="backslashreplace",
    )

    stderr.reconfigure.assert_called_once_with(
        encoding="utf-8",
        errors="backslashreplace",
    )


def test_configure_output_encoding_supports_streams_without_reconfigure(
    monkeypatch,
):
    stdout = io.StringIO()
    stderr = io.StringIO()

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", stdout)
        patch.setattr(sys, "stderr", stderr)

        cli.configure_output_encoding()

        print("Unknown — insufficient evidence.")
        print("Diagnostic output — preserved.", file=sys.stderr)

    assert stdout.getvalue() == "Unknown — insufficient evidence.\n"
    assert stderr.getvalue() == "Diagnostic output — preserved.\n"


def test_configure_output_encoding_ignores_non_callable_reconfigure(
    monkeypatch,
):
    stdout = SimpleNamespace(reconfigure=None)
    stderr = SimpleNamespace(reconfigure="unsupported")

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", stdout)
        patch.setattr(sys, "stderr", stderr)

        cli.configure_output_encoding()


def test_redirected_output_preserves_unicode(monkeypatch):
    stdout_buffer = io.BytesIO()
    stderr_buffer = io.BytesIO()

    stdout = io.TextIOWrapper(
        stdout_buffer,
        encoding="cp1255",
        errors="replace",
        newline="\n",
    )

    stderr = io.TextIOWrapper(
        stderr_buffer,
        encoding="cp1255",
        errors="replace",
        newline="\n",
    )

    message = "Unknown — insufficient evidence. ✓"

    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "stdout", stdout)
            patch.setattr(sys, "stderr", stderr)

            cli.configure_output_encoding()

            print(message)
            print(message, file=sys.stderr)

            stdout.flush()
            stderr.flush()

        assert stdout.encoding == "utf-8"
        assert stderr.encoding == "utf-8"

        assert stdout.errors == "backslashreplace"
        assert stderr.errors == "backslashreplace"

        assert stdout_buffer.getvalue() == (message + "\n").encode("utf-8")
        assert stderr_buffer.getvalue() == (message + "\n").encode("utf-8")

    finally:
        stdout.close()
        stderr.close()


def test_main_preserves_unicode_diagnosis(runtime, capsys):
    diagnosis = "Unknown — insufficient evidence. ✓"

    runtime.investigate.return_value = SimpleNamespace(
        diagnosis=diagnosis,
        completed=False,
    )

    exit_code = cli.main(["--ci", "build-1423"])

    assert exit_code == cli.EXIT_INCOMPLETE

    output = capsys.readouterr()

    assert diagnosis in output.out
    assert output.err == ""
