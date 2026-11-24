"""Regression tests for the standalone CI extraction helper."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from common.ci_extraction import extract_failure_section

PROJECT_ROOT = Path(__file__).resolve().parents[2]

HELPER_PATH = PROJECT_ROOT / "skills" / "k8s-triage" / "scripts" / "extract_ci_error.py"

FIXTURES_DIR = PROJECT_ROOT / "fixtures" / "ci"

MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024


def run_helper(
    path: Path,
    *,
    json_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute the helper as an independent CLI process."""

    command = [
        sys.executable,
        "-I",
        "-S",
        "-X",
        "utf8",
        str(HELPER_PATH),
        str(path),
    ]

    if json_output:
        command.append("--json")

    return subprocess.run(
        command,
        cwd=str(path.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    ("filename", "evidence"),
    [
        ("build-1423.log", "assert 201 == 400"),
        ("build-1424.log", "/requirements.txt"),
        ("build-1425.log", "nil pointer"),
    ],
)
def test_real_ci_fixtures(
    filename: str,
    evidence: str,
) -> None:
    """Preserve expected evidence in every CI fixture."""

    path = FIXTURES_DIR / filename

    process = run_helper(path)

    assert process.returncode == 0
    assert not process.stderr

    result = json.loads(process.stdout)

    expected = extract_failure_section(path.read_text(encoding="utf-8"))

    assert result["logs"] == expected["text"]
    assert result["matched_lines"] == expected["matched_lines"]
    assert result["selected_lines"] == expected["selected_lines"]
    assert evidence in result["logs"]
    assert result["truncated"] is False


@pytest.mark.parametrize(
    "newline",
    ["\n", "\r\n"],
    ids=["LF", "CRLF"],
)
def test_no_failure_markers(
    tmp_path: Path,
    newline: str,
) -> None:
    """Preserve logs and their original line endings."""

    path = tmp_path / "successful.log"

    logs = newline.join(["Starting build", "Build completed"])

    path.write_bytes(logs.encode("utf-8"))

    process = run_helper(path)

    assert process.returncode == 0

    result = json.loads(process.stdout)

    assert result["failure_markers_found"] is False
    assert result["matched_lines"] == 0
    assert result["logs"] == logs
    assert result["returned_bytes"] == len(logs.encode("utf-8"))


def test_empty_log(tmp_path: Path) -> None:
    """Handle empty logs without inventing evidence."""

    path = tmp_path / "empty.log"
    path.write_bytes(b"")

    process = run_helper(path)

    assert process.returncode == 0

    result = json.loads(process.stdout)

    assert result["total_lines"] == 0
    assert result["matched_lines"] == 0
    assert result["logs"] == ""


def test_missing_file(tmp_path: Path) -> None:
    """Return a controlled error for nonexistent files."""

    process = run_helper(tmp_path / "missing.log")

    assert process.returncode == 1
    assert "Error:" in process.stderr
    assert "Traceback" not in process.stderr
    assert not process.stdout


def test_directory_rejected(tmp_path: Path) -> None:
    """Reject directories instead of reading them."""

    directory = tmp_path / "logs"
    directory.mkdir()

    process = run_helper(directory)

    assert process.returncode == 1
    assert "not a regular file" in process.stderr
    assert "Traceback" not in process.stderr


def test_oversized_input(tmp_path: Path) -> None:
    """Enforce the input size limit."""

    path = tmp_path / "oversized.log"

    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))

    process = run_helper(path)

    assert process.returncode == 1
    assert "input limit" in process.stderr
    assert "Traceback" not in process.stderr


def test_invalid_utf8(tmp_path: Path) -> None:
    """Reject malformed UTF-8 with a sanitized error."""

    path = tmp_path / "invalid.log"

    path.write_bytes(b"\xff\xfe\xff")

    process = run_helper(path)

    assert process.returncode == 1
    assert "UTF-8" in process.stderr
    assert "Traceback" not in process.stderr


def test_unicode_output_truncation(
    tmp_path: Path,
) -> None:
    """Bound extracted text while preserving valid UTF-8."""

    path = tmp_path / "large.log"

    logs = "ERROR: " + "בדיקה" * 5000 + "\nERROR: Final diagnostic evidence"

    path.write_text(logs, encoding="utf-8")

    process = run_helper(path)

    assert process.returncode == 0

    result = json.loads(process.stdout)

    assert result["truncated"] is True

    actual_bytes = len(result["logs"].encode("utf-8"))

    assert actual_bytes <= MAX_OUTPUT_BYTES
    assert actual_bytes == result["returned_bytes"]

    assert "ERROR: Final diagnostic evidence" in result["logs"]


def test_human_readable_output(
    tmp_path: Path,
) -> None:
    """Provide readable evidence without JSON mode."""

    path = tmp_path / "failed.log"

    path.write_text(
        "ERROR: Build failed",
        encoding="utf-8",
    )

    process = run_helper(
        path,
        json_output=False,
    )

    assert process.returncode == 0
    assert "File: failed.log" in process.stdout
    assert "Failure markers: 1" in process.stdout
    assert "ERROR: Build failed" in process.stdout


def test_no_markers_warning(
    tmp_path: Path,
) -> None:
    """Avoid treating missing failure markers as success."""

    path = tmp_path / "unknown.log"

    path.write_text(
        "Build started",
        encoding="utf-8",
    )

    process = run_helper(
        path,
        json_output=False,
    )

    assert process.returncode == 0

    assert "This does not establish that the job succeeded." in process.stdout
