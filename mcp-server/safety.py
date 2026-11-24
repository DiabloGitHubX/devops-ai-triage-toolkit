"""Reusable safety controls for MCP tool operations."""

import json
import re
from pathlib import Path
from typing import Any

from config import MAX_LOG_TAIL

DNS_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")

JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class SafetyError(ValueError):
    """Raised when a tool request violates a safety boundary."""


def validate_namespace(
    namespace: str,
    allowed_namespaces: frozenset[str],
) -> str:
    """Reject namespaces outside the configured allowlist."""

    if not isinstance(namespace, str):
        raise SafetyError("Namespace must be a string")

    if namespace not in allowed_namespaces:
        raise SafetyError("Namespace access denied by the configured allowlist")

    return namespace


def validate_resource_name(
    name: str,
    field: str = "resource name",
) -> str:
    """Validate a Kubernetes DNS subdomain resource name."""

    if not isinstance(name, str):
        raise SafetyError(f"{field} must be a string")

    if not name or len(name) > 253:
        raise SafetyError(f"Invalid {field}")

    if not all(DNS_LABEL_PATTERN.fullmatch(label) for label in name.split(".")):
        raise SafetyError(f"Invalid {field}")

    return name


def validate_container_name(name: str) -> str:
    """Validate a Kubernetes container name."""

    if not isinstance(name, str):
        raise SafetyError("Container name must be a string")

    if not DNS_LABEL_PATTERN.fullmatch(name):
        raise SafetyError("Invalid container name")

    return name


def validate_tail_lines(tail_lines: int) -> int:
    """Enforce the maximum permitted log tail."""

    if type(tail_lines) is not int:
        raise SafetyError("tail_lines must be an integer")

    if not 1 <= tail_lines <= MAX_LOG_TAIL:
        raise SafetyError(f"tail_lines must be between 1 and {MAX_LOG_TAIL}")

    return tail_lines


def validate_label_selector(
    selector: str | None,
) -> str | None:
    """Bound selector input before passing it to Kubernetes."""

    if selector is None:
        return None

    if not isinstance(selector, str):
        raise SafetyError("Label selector must be a string")

    if len(selector) > 1024:
        raise SafetyError("Label selector exceeds maximum length")

    if any(ord(character) < 32 for character in selector):
        raise SafetyError("Label selector contains control characters")

    return selector


def resolve_ci_log_path(
    fixtures_dir: Path,
    job_id: str,
) -> Path:
    """Resolve a CI log without allowing path traversal."""

    if not isinstance(job_id, str):
        raise SafetyError("Job identifier must be a string")

    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise SafetyError("Invalid CI job identifier")

    root = fixtures_dir.resolve()
    candidate = (root / f"{job_id}.log").resolve()

    if not candidate.is_relative_to(root):
        raise SafetyError("CI fixture path escapes the allowed directory")

    if not candidate.is_file():
        raise SafetyError("CI log fixture not found")

    return candidate


def truncate_text(
    text: str,
    max_bytes: int,
    *,
    keep_tail: bool = False,
) -> dict[str, Any]:
    """Bound UTF-8 text and explicitly report truncation."""

    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    encoded = text.encode("utf-8")
    original_bytes = len(encoded)

    if original_bytes <= max_bytes:
        return {
            "text": text,
            "truncated": False,
            "original_bytes": original_bytes,
            "returned_bytes": original_bytes,
        }

    if keep_tail:
        selected = encoded[-max_bytes:]
    else:
        selected = encoded[:max_bytes]

    result = selected.decode("utf-8", errors="ignore")

    return {
        "text": result,
        "truncated": True,
        "original_bytes": original_bytes,
        "returned_bytes": len(result.encode("utf-8")),
    }


def _json_size(payload: dict[str, Any]) -> int:
    """Measure serialized JSON payload size in UTF-8 bytes."""

    return len(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    )


def bound_response(
    payload: dict[str, Any],
    max_bytes: int,
) -> dict[str, Any]:
    """Enforce a final serialized response payload size limit."""

    if _json_size(payload) <= max_bytes:
        return payload

    original_size = _json_size(payload)

    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
    )

    result = {
        "truncated": True,
        "original_bytes": original_size,
        "message": (
            "Response exceeded the configured size limit. "
            "Use a narrower query for more complete evidence."
        ),
        "preview": "",
    }

    if _json_size(result) > max_bytes:
        raise SafetyError("Response size limit is too small")

    low = 0
    high = min(len(serialized), max_bytes)

    while low < high:
        middle = (low + high + 1) // 2
        result["preview"] = serialized[:middle]

        if _json_size(result) <= max_bytes:
            low = middle
        else:
            high = middle - 1

    result["preview"] = serialized[:low]

    return result
