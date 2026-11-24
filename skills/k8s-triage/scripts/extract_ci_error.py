"""Extract CI failure evidence without Kubernetes or LLM access."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.ci_extraction import extract_failure_section

MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024


class ExtractionError(RuntimeError):
    """A sanitized offline extraction error."""


def read_log(path: Path) -> str:
    """Read a bounded UTF-8 log file."""

    try:
        if not path.is_file():
            raise ExtractionError("The requested log is not a regular file.")

        if path.stat().st_size > MAX_FILE_BYTES:
            raise ExtractionError("CI log exceeds the 1 MiB input limit.")

        with path.open("rb") as file:
            raw = file.read(MAX_FILE_BYTES + 1)

    except OSError:
        raise ExtractionError("Unable to read the requested CI log.") from None

    if len(raw) > MAX_FILE_BYTES:
        raise ExtractionError("CI log exceeds the 1 MiB input limit.")

    try:
        return raw.decode("utf-8")

    except UnicodeDecodeError:
        raise ExtractionError("CI log is not valid UTF-8 text.") from None


def extract_log(path: Path) -> dict[str, Any]:
    """Extract bounded failure evidence from a local log."""

    logs = read_log(path)
    extracted = extract_failure_section(logs)

    encoded = extracted["text"].encode("utf-8")
    truncated = len(encoded) > MAX_OUTPUT_BYTES

    if truncated:
        text = encoded[-MAX_OUTPUT_BYTES:].decode(
            "utf-8",
            errors="ignore",
        )
    else:
        text = extracted["text"]

    return {
        "filename": path.name,
        "total_lines": len(logs.splitlines()),
        "failure_markers_found": extracted["failure_markers_found"],
        "matched_lines": extracted["matched_lines"],
        "selected_lines": extracted["selected_lines"],
        "truncated": truncated,
        "returned_bytes": len(text.encode("utf-8")),
        "logs": text,
    }


def build_parser() -> argparse.ArgumentParser:
    """Define the offline helper command-line interface."""

    parser = argparse.ArgumentParser(
        description=("Extract CI failure markers and surrounding diagnostic context.")
    )

    parser.add_argument(
        "log_file",
        type=Path,
        help="Path to a local UTF-8 CI log file.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Return structured JSON output.",
    )

    return parser


def main() -> int:
    """Run deterministic offline CI evidence extraction."""

    args = build_parser().parse_args()

    try:
        result = extract_log(args.log_file)

    except ExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                result,
                ensure_ascii=True,
                indent=2,
            )
        )

    else:
        print(f"File: {result['filename']}")
        print(f"Total lines: {result['total_lines']}")
        print(f"Selected lines: {result['selected_lines']}")
        print(f"Failure markers: {result['matched_lines']}")
        print(f"Truncated: {result['truncated']}")
        print()

        if not result["failure_markers_found"]:
            print(
                "No failure markers detected. "
                "This does not establish that the job succeeded."
            )
            print()

        if result["truncated"]:
            print("Warning: Extracted evidence was truncated.")
            print()

        print(result["logs"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
