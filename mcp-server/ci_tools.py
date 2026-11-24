"""Read-only CI log diagnostic operations for the MCP server."""

import re
from typing import Any

from config import Settings
from safety import (
    SafetyError,
    bound_response,
    resolve_ci_log_path,
    truncate_text,
)

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


class CIToolError(RuntimeError):
    """A sanitized CI diagnostic error."""


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


class CITools:
    """Read-only CI diagnostics with bounded local file access."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_ci_log(
        self,
        job_id: str,
        failing_section_only: bool = False,
    ) -> dict[str, Any]:
        """Retrieve a CI fixture or its relevant failure evidence."""

        if type(failing_section_only) is not bool:
            raise SafetyError("failing_section_only must be a boolean")

        path = resolve_ci_log_path(
            self.settings.ci_fixtures_dir,
            job_id,
        )

        try:
            if path.stat().st_size > self.settings.max_ci_file_bytes:
                raise CIToolError("CI log exceeds the configured file size limit.")

            with path.open("rb") as file:
                raw = file.read(self.settings.max_ci_file_bytes + 1)

        except OSError:
            raise CIToolError("Unable to read the requested CI log.") from None

        if len(raw) > self.settings.max_ci_file_bytes:
            raise CIToolError("CI log exceeds the configured file size limit.")

        try:
            logs = raw.decode("utf-8")

        except UnicodeDecodeError:
            raise CIToolError("CI log is not valid UTF-8 text.") from None

        total_lines = len(logs.splitlines())

        if failing_section_only:
            extracted = extract_failure_section(logs)
            selected_text = extracted["text"]

            failure_markers_found = extracted["failure_markers_found"]

            matched_lines = extracted["matched_lines"]
            selected_lines = extracted["selected_lines"]

        else:
            selected_text = logs
            failure_markers_found = None
            matched_lines = None
            selected_lines = total_lines

        text_limit = max(
            1,
            self.settings.max_response_bytes // 2,
        )

        result = truncate_text(
            selected_text,
            text_limit,
            keep_tail=True,
        )

        payload = {
            "job_id": job_id,
            "filename": path.name,
            "failing_section_only": failing_section_only,
            "failure_markers_found": failure_markers_found,
            "matched_lines": matched_lines,
            "total_lines": total_lines,
            "selected_lines": selected_lines,
            "source_bytes": len(raw),
            "logs": result["text"],
            "truncated": result["truncated"],
            "returned_bytes": result["returned_bytes"],
        }

        return bound_response(
            payload,
            self.settings.max_response_bytes,
        )
