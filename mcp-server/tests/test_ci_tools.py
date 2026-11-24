"""Tests for CI diagnostic operations and file access boundaries."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from ci_tools import CIToolError, CITools, extract_failure_section
from config import Settings
from safety import SafetyError, resolve_ci_log_path

# ============================================================
# CI fixture path security
# ============================================================


def test_valid_ci_fixture_path(fixture_dir: Path) -> None:
    path = fixture_dir / "build-1423.log"
    path.write_text("CI diagnostic evidence", encoding="utf-8")

    assert (
        resolve_ci_log_path(
            fixture_dir,
            "build-1423",
        )
        == path.resolve()
    )


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        ".",
        "..",
        "../secret",
        "../../.env",
        "../build-1423",
        r"..\secret",
        "/etc/passwd",
        r"C:\Windows\System32",
        "build-1423.log",
        "build-1423/other",
        "build 1423",
        "build\n1423",
        "build\x00",
        "%2e%2e%2fsecret",
        "-build",
        "_build",
        "a" * 129,
    ],
)
def test_invalid_ci_job_identifier(
    fixture_dir: Path,
    job_id: str,
) -> None:
    with pytest.raises(
        SafetyError,
        match="Invalid CI job identifier",
    ):
        resolve_ci_log_path(fixture_dir, job_id)


@pytest.mark.parametrize(
    "job_id",
    [None, 123, True, [], {}],
)
def test_invalid_ci_job_identifier_type(
    fixture_dir: Path,
    job_id: object,
) -> None:
    with pytest.raises(
        SafetyError,
        match="must be a string",
    ):
        resolve_ci_log_path(fixture_dir, job_id)


def test_missing_ci_fixture(fixture_dir: Path) -> None:
    with pytest.raises(
        SafetyError,
        match="fixture not found",
    ):
        resolve_ci_log_path(
            fixture_dir,
            "nonexistent-build",
        )


def test_directory_is_not_a_valid_fixture(
    fixture_dir: Path,
) -> None:
    (fixture_dir / "build-1423.log").mkdir()

    with pytest.raises(
        SafetyError,
        match="fixture not found",
    ):
        resolve_ci_log_path(
            fixture_dir,
            "build-1423",
        )


def test_symlink_cannot_escape_fixture_directory(
    fixture_dir: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.log"
    outside.write_text(
        "SYNTHETIC_PRIVATE_CONTENT",
        encoding="utf-8",
    )

    link = fixture_dir / "build-1423.log"

    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic link creation is unavailable on this platform or account")

    with pytest.raises(
        SafetyError,
        match="escapes the allowed directory",
    ):
        resolve_ci_log_path(
            fixture_dir,
            "build-1423",
        )


# ============================================================
# Failure evidence extraction
# ============================================================


def test_failure_extraction_without_markers() -> None:
    logs = "INFO: Starting\nINFO: Completed successfully\n"

    result = extract_failure_section(logs)

    assert result["text"] == logs
    assert result["failure_markers_found"] is False
    assert result["matched_lines"] == 0
    assert result["selected_lines"] == 2


def test_failure_extraction_empty_log() -> None:
    result = extract_failure_section("")

    assert result["text"] == ""
    assert result["failure_markers_found"] is False
    assert result["matched_lines"] == 0
    assert result["selected_lines"] == 0


@pytest.mark.parametrize(
    "marker",
    [
        "ERROR: Application unavailable",
        "FAILED tests/test_app.py",
        "Job conclusion: FAILURE",
        "FATAL: Unable to start",
        "Unhandled exception",
        "Traceback (most recent call last)",
        "assert response.status_code == 400",
        "Process completed with exit code 1",
        "File not found",
        "nil pointer evaluating interface",
        "Permission denied",
        "Connection timed out",
    ],
)
def test_failure_marker_detection(marker: str) -> None:
    result = extract_failure_section(marker)

    assert result["failure_markers_found"] is True
    assert result["matched_lines"] == 1
    assert result["selected_lines"] == 1
    assert marker in result["text"]


def test_failure_extraction_preserves_context() -> None:
    lines = [f"INFO: Line {index}" for index in range(100)]

    lines[50] = "ERROR: Application failure"

    result = extract_failure_section("\n".join(lines))

    assert result["failure_markers_found"] is True
    assert result["matched_lines"] == 1
    assert result["selected_lines"] == 21

    assert "INFO: Line 45" in result["text"]
    assert "ERROR: Application failure" in result["text"]
    assert "INFO: Line 65" in result["text"]

    assert "INFO: Line 44\n" not in result["text"]
    assert "INFO: Line 66" not in result["text"]


def test_overlapping_failure_context_is_merged() -> None:
    lines = [f"INFO: Line {index}" for index in range(100)]

    lines[40] = "ERROR: First problem"
    lines[45] = "ERROR: Second problem"

    result = extract_failure_section("\n".join(lines))

    assert result["matched_lines"] == 2
    assert result["selected_lines"] == 26
    assert result["text"].count("--- Lines ") == 1
    assert "ERROR: First problem" in result["text"]
    assert "ERROR: Second problem" in result["text"]


def test_separate_failure_sections_are_preserved() -> None:
    lines = [f"INFO: Line {index}" for index in range(100)]

    lines[10] = "ERROR: First problem"
    lines[80] = "ERROR: Second problem"

    result = extract_failure_section("\n".join(lines))

    assert result["matched_lines"] == 2
    assert result["selected_lines"] == 42
    assert result["text"].count("--- Lines ") == 2


# ============================================================
# CI tool operations
# ============================================================


def test_full_ci_log_retrieval(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    logs = "INFO: Starting\nERROR: Build failed\n"

    (fixture_dir / "build-1423.log").write_bytes(logs.encode("utf-8"))

    result = CITools(settings).get_ci_log("build-1423")

    assert result["job_id"] == "build-1423"
    assert result["filename"] == "build-1423.log"
    assert result["logs"] == logs
    assert result["total_lines"] == 2
    assert result["selected_lines"] == 2
    assert result["source_bytes"] == len(logs.encode("utf-8"))
    assert result["failing_section_only"] is False
    assert result["failure_markers_found"] is None
    assert result["truncated"] is False


@pytest.mark.parametrize(
    "value",
    [None, 0, 1, "true", "false", [], {}],
)
def test_invalid_failure_section_argument(
    settings: Settings,
    value: object,
) -> None:
    with pytest.raises(
        SafetyError,
        match="must be a boolean",
    ):
        CITools(settings).get_ci_log(
            "build-1423",
            failing_section_only=value,
        )


def test_oversized_ci_file_is_rejected(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    limited_settings = replace(
        settings,
        max_ci_file_bytes=1024,
    )

    (fixture_dir / "build-1423.log").write_bytes(b"a" * 1025)

    with pytest.raises(
        CIToolError,
        match="file size limit",
    ):
        CITools(limited_settings).get_ci_log("build-1423")


def test_ci_file_at_exact_size_limit(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    limited_settings = replace(
        settings,
        max_ci_file_bytes=1024,
    )

    (fixture_dir / "build-1423.log").write_bytes(b"a" * 1024)

    result = CITools(limited_settings).get_ci_log("build-1423")

    assert result["source_bytes"] == 1024
    assert result["truncated"] is False


def test_invalid_utf8_ci_log(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    (fixture_dir / "build-1423.log").write_bytes(b"\xff\xfe\xff")

    with pytest.raises(
        CIToolError,
        match="not valid UTF-8",
    ):
        CITools(settings).get_ci_log("build-1423")


def test_large_ci_response_is_truncated(
    settings: Settings,
    fixture_dir: Path,
) -> None:
    limited_settings = replace(
        settings,
        max_response_bytes=1024,
    )

    error = "ERROR: Final build failure"

    logs = ("INFO: Processing\n" * 1000) + error

    (fixture_dir / "build-1423.log").write_bytes(logs.encode("utf-8"))

    result = CITools(limited_settings).get_ci_log("build-1423")

    serialized = json.dumps(
        result,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")

    assert result["truncated"] is True
    assert len(serialized) <= 1024
    assert result["logs"].endswith(error)
    assert result["returned_bytes"] <= 512


# ============================================================
# Committed synthetic CI fixture regression tests
# ============================================================


@pytest.mark.parametrize(
    ("job_id", "expected_evidence"),
    [
        ("build-1423", "assert 201 == 400"),
        ("build-1424", '"/requirements.txt": not found'),
        ("build-1425", "nil pointer evaluating interface"),
    ],
)
def test_committed_ci_fixture_evidence(
    settings: Settings,
    real_ci_fixture_dir: Path,
    job_id: str,
    expected_evidence: str,
) -> None:
    fixture_settings = replace(
        settings,
        ci_fixtures_dir=real_ci_fixture_dir,
    )

    tools = CITools(fixture_settings)

    full = tools.get_ci_log(job_id)

    extracted = tools.get_ci_log(
        job_id,
        failing_section_only=True,
    )

    assert expected_evidence in full["logs"]
    assert expected_evidence in extracted["logs"]

    assert extracted["failure_markers_found"] is True
    assert extracted["matched_lines"] > 0
    assert extracted["selected_lines"] < full["total_lines"]
    assert extracted["truncated"] is False


def test_resolved_path_outside_fixture_directory_is_rejected(
    fixture_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify containment without requiring OS symlink privileges."""

    root = fixture_dir.resolve()
    candidate = root / "build-1423.log"

    outside = tmp_path / "outside.log"
    outside.write_text(
        "SYNTHETIC_PRIVATE_CONTENT",
        encoding="utf-8",
    )

    outside = outside.resolve()

    original_resolve = Path.resolve

    def simulated_resolve(
        self: Path,
        *args,
        **kwargs,
    ) -> Path:
        if self == candidate:
            return outside

        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(
        Path,
        "resolve",
        simulated_resolve,
    )

    with pytest.raises(
        SafetyError,
        match="escapes the allowed directory",
    ):
        resolve_ci_log_path(
            fixture_dir,
            "build-1423",
        )
