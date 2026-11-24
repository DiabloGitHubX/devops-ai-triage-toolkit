"""Deterministic CI failure evidence extraction."""

import re
from typing import Any

FAILURE_PATTERN = re.compile(
    r"\b(?:error|failed|failure|fatal|exception|traceback)\b"
    r"|assert\s+"
    r"|exit code\s+[1-9]\d*"
    r"|not found"
    r"|nil pointer"
    r"|permission denied"
    r"|timed out",
    re.IGNORECASE,
)

CONTEXT_BEFORE = 5
CONTEXT_AFTER = 15


def extract_failure_section(
    logs: str,
) -> dict[str, Any]:
    """Extract failure markers and surrounding diagnostic context."""

    lines = logs.splitlines()

    matches = [
        index for index, line in enumerate(lines) if FAILURE_PATTERN.search(line)
    ]

    if not matches:
        return {
            "text": logs,
            "failure_markers_found": False,
            "matched_lines": 0,
            "selected_lines": len(lines),
        }

    ranges: list[tuple[int, int]] = []

    for index in matches:
        start = max(0, index - CONTEXT_BEFORE)

        end = min(
            len(lines),
            index + CONTEXT_AFTER + 1,
        )

        if ranges and start <= ranges[-1][1]:
            previous_start, previous_end = ranges[-1]

            ranges[-1] = (
                previous_start,
                max(previous_end, end),
            )
        else:
            ranges.append((start, end))

    sections = []
    selected_lines = 0

    for start, end in ranges:
        section = "\n".join(lines[start:end])

        sections.append(f"--- Lines {start + 1}-{end} ---\n{section}")

        selected_lines += end - start

    return {
        "text": "\n\n".join(sections),
        "failure_markers_found": True,
        "matched_lines": len(matches),
        "selected_lines": selected_lines,
    }
