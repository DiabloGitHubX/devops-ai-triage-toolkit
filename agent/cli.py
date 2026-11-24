"""Command-line interface for the read-only diagnostic agent."""

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence

from agent.agent_loop import (
    MAX_QUERY_BYTES,
    DiagnosticAgent,
    InvestigationResult,
)
from agent.config import (
    AgentSettings,
    ConfigurationError,
    load_settings,
    load_skill,
)
from agent.llm_client import (
    DiagnosticLLMClient,
    LLMClientError,
)
from agent.mcp_client import (
    MCPClientError,
    connect_mcp,
)
from agent.trace import configure_trace_logging

EXIT_SUCCESS = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE_ERROR = 2
EXIT_RUNTIME_ERROR = 3
EXIT_INTERRUPTED = 130

NAMESPACE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

POD_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*"
)

CI_JOB_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def configure_output_encoding() -> None:
    """Use UTF-8 for CLI output, including redirected Windows streams."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)

        if callable(reconfigure):
            reconfigure(
                encoding="utf-8",
                errors="backslashreplace",
            )


def namespace_argument(value: str) -> str:
    """Validate a Kubernetes namespace argument."""

    if not NAMESPACE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("Invalid Kubernetes namespace.")

    return value


def pod_argument(value: str) -> str:
    """Validate a Kubernetes pod or workload name."""

    if len(value) > 253 or not POD_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("Invalid Kubernetes pod or workload name.")

    return value


def ci_job_argument(value: str) -> str:
    """Validate a CI fixture identifier."""

    if not CI_JOB_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "Invalid CI job ID. Use an identifier without a path or file extension."
        )

    return value


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""

    parser = argparse.ArgumentParser(
        prog="python -m agent",
        description=(
            "Read-only Kubernetes and CI failure diagnostics "
            "using an LLM, MCP tools and a triage Skill."
        ),
        epilog=("The agent suggests remediation but never executes it."),
        allow_abbrev=False,
    )

    targets = parser.add_mutually_exclusive_group()

    targets.add_argument(
        "--ci",
        metavar="JOB_ID",
        type=ci_job_argument,
        help="Investigate a failed CI job.",
    )

    targets.add_argument(
        "--pod",
        metavar="NAME",
        type=pod_argument,
        help="Investigate a Kubernetes pod or workload.",
    )

    parser.add_argument(
        "--namespace",
        metavar="NAMESPACE",
        type=namespace_argument,
        help=(
            "Kubernetes namespace for a pod or natural-language "
            "investigation. Defaults to agent configuration."
        ),
    )

    parser.add_argument(
        "query",
        nargs="?",
        help="Natural-language diagnostic request.",
    )

    return parser


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse and validate the selected investigation mode."""

    parser = build_parser()
    args = parser.parse_args(argv)

    selected_modes = sum(
        value is not None
        for value in (
            args.ci,
            args.pod,
            args.query,
        )
    )

    if selected_modes != 1:
        parser.error(
            "Specify exactly one investigation target: "
            "--ci, --pod or a natural-language query."
        )

    if args.ci is not None and args.namespace is not None:
        parser.error("--namespace cannot be combined with --ci.")

    if args.query is not None:
        args.query = args.query.strip()

        if not args.query:
            parser.error("The investigation query must not be empty.")

        if len(args.query.encode("utf-8")) > MAX_QUERY_BYTES:
            parser.error("The investigation query exceeds the size limit.")

    return args


def build_query(
    args: argparse.Namespace,
    default_namespace: str,
) -> str:
    """Convert CLI arguments into a diagnostic request."""

    namespace = args.namespace or default_namespace

    if args.ci is not None:
        return (
            f"Investigate failed CI job {args.ci}. "
            "Retrieve its failure evidence, identify the "
            "root cause and suggest a fix. "
            "Do not execute remediation."
        )

    if args.pod is not None:
        return (
            f"Investigate Kubernetes pod or workload "
            f"{args.pod} in namespace {namespace}. "
            "Discover the exact pod name if necessary. "
            "Collect diagnostic evidence, identify the "
            "root cause and suggest a fix. "
            "Do not execute remediation."
        )

    if args.namespace is not None:
        return f"Requested Kubernetes namespace: {namespace}.\n{args.query}"

    return args.query


async def run_investigation(
    settings: AgentSettings,
    skill: str,
    query: str,
) -> InvestigationResult:
    """Manage the MCP and LLM client lifecycles."""

    async with (
        connect_mcp(
            timeout_seconds=settings.mcp_timeout,
        ) as mcp,
        DiagnosticLLMClient(settings) as llm,
    ):
        agent = DiagnosticAgent(
            settings=settings,
            skill=skill,
            llm=llm,
            mcp=mcp,
        )

        return await agent.investigate(query)


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the diagnostic CLI and return a process exit code."""

    configure_output_encoding()

    args = parse_arguments(argv)

    try:
        settings = load_settings()
        skill = load_skill(settings.skill_path)

        query = build_query(
            args,
            settings.default_namespace,
        )

        if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
            print(
                "Error: Generated investigation query exceeds the size limit.",
                file=sys.stderr,
            )

            return EXIT_USAGE_ERROR

        configure_trace_logging()

        result = asyncio.run(
            run_investigation(
                settings,
                skill,
                query,
            )
        )

    except ConfigurationError:
        print(
            "Error: Invalid agent configuration or Skill. "
            "Check the local configuration against "
            ".env.example.",
            file=sys.stderr,
        )

        return EXIT_USAGE_ERROR

    except MCPClientError:
        print(
            "Error: Unable to initialize or use the MCP diagnostic server.",
            file=sys.stderr,
        )

        return EXIT_RUNTIME_ERROR

    except LLMClientError:
        print(
            "Error: Unable to initialize or use the configured LLM provider.",
            file=sys.stderr,
        )

        return EXIT_RUNTIME_ERROR

    except KeyboardInterrupt:
        print(
            "Investigation interrupted.",
            file=sys.stderr,
        )

        return EXIT_INTERRUPTED

    except Exception:  # noqa: BLE001
        # Do not expose raw exception messages, credentials,
        # provider responses or internal stack traces.
        print(
            "Error: Investigation failed unexpectedly. "
            "Review the local configuration and execution trace.",
            file=sys.stderr,
        )

        return EXIT_RUNTIME_ERROR

    print(result.diagnosis)

    if result.completed:
        return EXIT_SUCCESS

    return EXIT_INCOMPLETE
