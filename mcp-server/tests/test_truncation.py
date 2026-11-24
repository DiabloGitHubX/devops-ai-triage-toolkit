"""Tests for bounded diagnostic text and serialized MCP payloads."""

import json

import pytest
from safety import SafetyError, bound_response, truncate_text


def serialized_size(payload: dict) -> int:
    """Measure the serialized diagnostic payload in bytes."""

    return len(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    )


# ============================================================
# Text truncation
# ============================================================


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        ("", 100),
        ("hello", 100),
        ("hello", 5),
        ("שלום", 8),
        ("🚀", 4),
    ],
)
def test_text_within_limit(text: str, limit: int) -> None:
    result = truncate_text(text, limit)

    assert result["text"] == text
    assert result["truncated"] is False
    assert result["original_bytes"] == len(text.encode("utf-8"))
    assert result["returned_bytes"] == len(text.encode("utf-8"))


def test_text_head_truncation() -> None:
    result = truncate_text("abcdefghij", 5)

    assert result["text"] == "abcde"
    assert result["truncated"] is True
    assert result["original_bytes"] == 10
    assert result["returned_bytes"] == 5


def test_text_tail_truncation() -> None:
    result = truncate_text(
        "abcdefghij",
        5,
        keep_tail=True,
    )

    assert result["text"] == "fghij"
    assert result["truncated"] is True
    assert result["original_bytes"] == 10
    assert result["returned_bytes"] == 5


def test_tail_preserves_recent_error_evidence() -> None:
    error = "ERROR: DATABASE_URL is missing"

    logs = ("INFO: Application starting\n" * 100) + error

    result = truncate_text(
        logs,
        128,
        keep_tail=True,
    )

    assert result["truncated"] is True
    assert result["text"].endswith(error)
    assert result["returned_bytes"] <= 128


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_invalid_text_byte_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        truncate_text("example", limit)


# ============================================================
# Unicode safety
# ============================================================


@pytest.mark.parametrize(
    "text",
    [
        "שלום עולם",
        "你好世界",
        "🚀🔥⚠️",
        "ASCII and שלום and 🚀",
    ],
)
@pytest.mark.parametrize("limit", [1, 2, 3, 5, 7])
@pytest.mark.parametrize("keep_tail", [False, True])
def test_unicode_truncation(
    text: str,
    limit: int,
    keep_tail: bool,
) -> None:
    result = truncate_text(
        text,
        limit,
        keep_tail=keep_tail,
    )

    encoded = result["text"].encode("utf-8")

    assert len(encoded) <= limit
    assert result["returned_bytes"] == len(encoded)
    assert result["original_bytes"] == len(text.encode("utf-8"))

    assert result["truncated"] is (len(text.encode("utf-8")) > limit)

    assert "\ufffd" not in result["text"]

    if keep_tail:
        assert text.endswith(result["text"])
    else:
        assert text.startswith(result["text"])


# ============================================================
# Serialized JSON response limits
# ============================================================


def test_small_response_preserved() -> None:
    payload = {
        "namespace": "staging",
        "count": 1,
        "pods": [{"name": "orders-api"}],
    }

    result = bound_response(payload, 1024)

    assert result == payload


def test_response_at_exact_byte_limit() -> None:
    payload = {"logs": "example"}

    limit = serialized_size(payload)

    assert bound_response(payload, limit) == payload


@pytest.mark.parametrize("limit", [1024, 2048, 8192, 32768])
def test_large_response_is_bounded(limit: int) -> None:
    payload = {
        "namespace": "staging",
        "logs": "ERROR: application failure\n" * 5000,
    }

    result = bound_response(payload, limit)

    assert result["truncated"] is True
    assert result["original_bytes"] == serialized_size(payload)
    assert serialized_size(result) <= limit
    assert isinstance(result["preview"], str)
    assert "narrower query" in result["message"]


@pytest.mark.parametrize(
    "text",
    [
        '"' * 10000,
        "\\" * 10000,
        "\n" * 10000,
        "שלום" * 10000,
        "🚀" * 10000,
    ],
)
def test_json_escaping_respects_byte_limit(text: str) -> None:
    payload = {"logs": text}

    result = bound_response(payload, 1024)

    assert result["truncated"] is True
    assert serialized_size(result) <= 1024
    assert result["original_bytes"] == serialized_size(payload)


def test_nested_response_is_bounded() -> None:
    payload = {
        "namespace": "staging",
        "pods": [
            {
                "name": f"pod-{index}",
                "message": "diagnostic evidence" * 100,
            }
            for index in range(100)
        ],
    }

    result = bound_response(payload, 2048)

    assert result["truncated"] is True
    assert serialized_size(result) <= 2048


def test_response_limit_too_small_for_metadata() -> None:
    with pytest.raises(
        SafetyError,
        match="Response size limit is too small",
    ):
        bound_response({"logs": "a" * 1000}, 10)


def test_response_truncation_does_not_mutate_input() -> None:
    payload = {
        "logs": "a" * 10000,
        "truncated": False,
    }

    original = payload.copy()

    result = bound_response(payload, 1024)

    assert result["truncated"] is True
    assert payload == original


def test_existing_truncation_metadata_is_preserved() -> None:
    payload = {
        "logs": "partial diagnostic evidence",
        "truncated": True,
        "original_bytes": 10000,
        "returned_bytes": 27,
    }

    result = bound_response(payload, 1024)

    assert result == payload
    assert result["truncated"] is True
