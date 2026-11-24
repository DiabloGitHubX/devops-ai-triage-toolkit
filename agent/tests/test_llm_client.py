"""Regression tests for the asynchronous LLM client."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion
from openai.types.completion_usage import CompletionUsage

from agent import llm_client
from agent.llm_client import (
    DiagnosticLLMClient,
    LLMClientError,
    RequestedToolCall,
    TokenUsage,
)

MESSAGES = [
    {
        "role": "system",
        "content": "You are a read-only diagnostic agent.",
    },
    {
        "role": "user",
        "content": "Investigate failed CI job build-1423.",
    },
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_ci_log",
            "description": "Retrieve CI diagnostic evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
    },
]


def make_tool_call(
    call_id="call-001",
    name="get_ci_log",
    arguments=None,
):
    """Construct a synthetic provider tool call."""

    if arguments is None:
        arguments = json.dumps({"job_id": "build-1423"})

    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def make_response(
    content="Diagnostic response.",
    tool_calls=None,
    finish_reason="stop",
    usage=None,
):
    """Construct a response using the actual SDK model."""

    return ChatCompletion(
        id="completion-test-001",
        object="chat.completion",
        created=1700000000,
        model="mock-model",
        choices=[
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
            }
        ],
        usage=usage,
    )


def make_usage(
    prompt_tokens=100,
    completion_tokens=25,
    total_tokens=125,
):
    """Construct synthetic provider usage metadata."""

    return CompletionUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


@pytest.fixture
def sdk_client():
    """Provide a mocked SDK client without network access."""

    client = MagicMock()

    client.chat.completions.create = AsyncMock(
        return_value=make_response(
            usage=make_usage(),
        )
    )

    client.close = AsyncMock()

    return client


@pytest.fixture
def client(settings, sdk_client):
    """Provide the diagnostic client with an injected SDK client."""

    return DiagnosticLLMClient(
        settings,
        client=sdk_client,
    )


def complete(client, messages=None, **kwargs):
    """Execute an asynchronous completion in an isolated event loop."""

    if messages is None:
        messages = MESSAGES

    return asyncio.run(client.complete(messages, **kwargs))


def test_owned_client_initialization(
    monkeypatch,
    settings,
    sdk_client,
):
    constructor = MagicMock(
        return_value=sdk_client,
    )

    monkeypatch.setattr(
        llm_client,
        "AsyncOpenAI",
        constructor,
    )

    DiagnosticLLMClient(settings)

    constructor.assert_called_once_with(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=float(settings.llm_timeout),
        max_retries=0,
    )


def test_injected_client_skips_constructor(
    monkeypatch,
    settings,
    sdk_client,
):
    constructor = MagicMock()

    monkeypatch.setattr(
        llm_client,
        "AsyncOpenAI",
        constructor,
    )

    DiagnosticLLMClient(
        settings,
        client=sdk_client,
    )

    constructor.assert_not_called()


def test_owned_client_context_closes_resources(
    monkeypatch,
    settings,
    sdk_client,
):
    monkeypatch.setattr(
        llm_client,
        "AsyncOpenAI",
        MagicMock(return_value=sdk_client),
    )

    async def exercise():
        diagnostic_client = DiagnosticLLMClient(
            settings,
        )

        async with diagnostic_client as entered:
            assert entered is diagnostic_client

    asyncio.run(exercise())

    sdk_client.close.assert_awaited_once()


def test_owned_client_closes_after_exception(
    monkeypatch,
    settings,
    sdk_client,
):
    monkeypatch.setattr(
        llm_client,
        "AsyncOpenAI",
        MagicMock(return_value=sdk_client),
    )

    async def exercise():
        async with DiagnosticLLMClient(settings):
            raise RuntimeError("Synthetic consumer failure")

    with pytest.raises(
        RuntimeError,
        match="Synthetic consumer failure",
    ):
        asyncio.run(exercise())

    sdk_client.close.assert_awaited_once()


def test_injected_client_remains_open(
    client,
    sdk_client,
):
    async def exercise():
        async with client:
            pass

        await client.close()

    asyncio.run(exercise())

    sdk_client.close.assert_not_awaited()


def test_default_request(
    client,
    sdk_client,
    settings,
):
    result = complete(client)

    sdk_client.chat.completions.create.assert_awaited_once_with(
        model=settings.llm_model,
        messages=MESSAGES,
        max_tokens=settings.max_output_tokens,
        timeout=float(settings.llm_timeout),
    )

    assert result.content == "Diagnostic response."
    assert result.finish_reason == "stop"
    assert result.tool_calls == ()

    assert result.usage == TokenUsage(
        prompt_tokens=100,
        completion_tokens=25,
        total_tokens=125,
    )


def test_custom_request_limits(
    client,
    sdk_client,
    settings,
):
    complete(
        client,
        max_output_tokens=512,
        timeout_seconds=15.0,
    )

    sdk_client.chat.completions.create.assert_awaited_once_with(
        model=settings.llm_model,
        messages=MESSAGES,
        max_tokens=512,
        timeout=15.0,
    )


def test_tool_enabled_request(
    client,
    sdk_client,
):
    complete(client, tools=TOOLS)

    request = sdk_client.chat.completions.create.await_args.kwargs

    assert request["tools"] == TOOLS
    assert request["tool_choice"] == "auto"


@pytest.mark.parametrize(
    "tools",
    [None, [], ()],
)
def test_finalization_omits_tool_parameters(
    client,
    sdk_client,
    tools,
):
    complete(client, tools=tools)

    request = sdk_client.chat.completions.create.await_args.kwargs

    assert "tools" not in request
    assert "tool_choice" not in request


def test_request_accepts_message_sequence(
    client,
    sdk_client,
):
    complete(
        client,
        messages=tuple(MESSAGES),
    )

    request = sdk_client.chat.completions.create.await_args.kwargs

    assert isinstance(request["messages"], list)
    assert request["messages"] == MESSAGES


@pytest.mark.parametrize(
    "messages",
    [[], ()],
)
def test_reject_empty_conversation(
    client,
    sdk_client,
    messages,
):
    with pytest.raises(
        LLMClientError,
        match="conversation must not be empty",
    ) as captured:
        complete(
            client,
            messages=messages,
        )

    assert captured.value.category == "invalid_request"
    assert captured.value.http_status is None

    sdk_client.chat.completions.create.assert_not_awaited()


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
        2049,
        512.0,
        "512",
        True,
        False,
    ],
)
def test_reject_invalid_output_limit(
    client,
    sdk_client,
    limit,
):
    with pytest.raises(
        LLMClientError,
        match="Invalid LLM output token limit",
    ) as captured:
        complete(
            client,
            max_output_tokens=limit,
        )

    assert captured.value.category == "invalid_request"
    assert captured.value.http_status is None

    sdk_client.chat.completions.create.assert_not_awaited()


@pytest.mark.parametrize(
    "limit",
    [1, 256, 2048],
)
def test_accept_output_limit_boundaries(
    client,
    sdk_client,
    limit,
):
    complete(
        client,
        max_output_tokens=limit,
    )

    request = sdk_client.chat.completions.create.await_args.kwargs

    assert request["max_tokens"] == limit


@pytest.mark.parametrize(
    "timeout",
    [
        0,
        -1,
        60.1,
        61,
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
)
def test_reject_invalid_timeout(
    client,
    sdk_client,
    timeout,
):
    with pytest.raises(
        LLMClientError,
        match="Invalid LLM request timeout",
    ) as captured:
        complete(
            client,
            timeout_seconds=timeout,
        )

    assert captured.value.category == "invalid_request"
    assert captured.value.http_status is None

    sdk_client.chat.completions.create.assert_not_awaited()


@pytest.mark.parametrize(
    "timeout",
    [0.1, 1.0, 30.0, 60.0],
)
def test_accept_valid_timeout(
    client,
    sdk_client,
    timeout,
):
    complete(
        client,
        timeout_seconds=timeout,
    )

    request = sdk_client.chat.completions.create.await_args.kwargs

    assert request["timeout"] == timeout


def test_normalize_single_tool_call(
    client,
    sdk_client,
):
    call = make_tool_call()

    sdk_client.chat.completions.create.return_value = make_response(
        content=None,
        tool_calls=[call],
        finish_reason="tool_calls",
        usage=make_usage(),
    )

    result = complete(client, tools=TOOLS)

    assert result.content is None
    assert result.finish_reason == "tool_calls"

    assert result.tool_calls == (
        RequestedToolCall(
            call_id="call-001",
            name="get_ci_log",
            arguments=call["function"]["arguments"],
        ),
    )


def test_normalize_multiple_tool_calls(
    client,
    sdk_client,
):
    calls = [
        make_tool_call(call_id="call-001"),
        make_tool_call(
            call_id="call-002",
            name="list_pods",
            arguments='{"namespace": "staging"}',
        ),
    ]

    sdk_client.chat.completions.create.return_value = make_response(
        content=None,
        tool_calls=calls,
        finish_reason="tool_calls",
    )

    result = complete(client, tools=TOOLS)

    assert len(result.tool_calls) == 2

    assert [call.call_id for call in result.tool_calls] == ["call-001", "call-002"]

    assert [call.name for call in result.tool_calls] == ["get_ci_log", "list_pods"]


def test_preserve_gemini_thought_signature(
    client,
    sdk_client,
):
    call = make_tool_call()

    call["extra_content"] = {
        "google": {
            "thought_signature": ("synthetic-provider-signature"),
        },
    }

    sdk_client.chat.completions.create.return_value = make_response(
        content=None,
        tool_calls=[call],
        finish_reason="tool_calls",
    )

    result = complete(client, tools=TOOLS)

    serialized_call = result.message["tool_calls"][0]

    assert serialized_call["extra_content"] == {
        "google": {
            "thought_signature": ("synthetic-provider-signature"),
        },
    }

    assert serialized_call["id"] == "call-001"


def test_preserve_serialized_assistant_message(
    client,
    sdk_client,
):
    sdk_client.chat.completions.create.return_value = make_response(
        content="Collected diagnostic evidence.",
    )

    result = complete(client)

    assert result.message["role"] == "assistant"

    assert result.message["content"] == ("Collected diagnostic evidence.")

    assert "tool_calls" not in result.message


def test_reject_duplicate_tool_call_ids(
    client,
    sdk_client,
):
    sdk_client.chat.completions.create.return_value = make_response(
        content=None,
        tool_calls=[
            make_tool_call(call_id="duplicate"),
            make_tool_call(call_id="duplicate"),
        ],
        finish_reason="tool_calls",
    )

    with pytest.raises(
        LLMClientError,
        match="duplicate tool-call identifiers",
    ) as captured:
        complete(client, tools=TOOLS)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


@pytest.mark.parametrize(
    ("call_id", "name"),
    [
        ("", "get_ci_log"),
        ("call-001", ""),
    ],
)
def test_reject_malformed_tool_calls(
    client,
    sdk_client,
    call_id,
    name,
):
    sdk_client.chat.completions.create.return_value = make_response(
        content=None,
        tool_calls=[
            make_tool_call(
                call_id=call_id,
                name=name,
            ),
        ],
        finish_reason="tool_calls",
    )

    with pytest.raises(
        LLMClientError,
        match="malformed tool call",
    ) as captured:
        complete(client, tools=TOOLS)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


def test_reject_non_string_tool_arguments(
    client,
    sdk_client,
):
    response = make_response(
        content=None,
        tool_calls=[make_tool_call()],
        finish_reason="tool_calls",
    )

    # Simulate malformed provider data after SDK parsing.
    response.choices[0].message.tool_calls[0].function.arguments = {
        "job_id": "build-1423"
    }

    sdk_client.chat.completions.create.return_value = response

    with pytest.raises(
        LLMClientError,
        match="malformed tool call",
    ) as captured:
        complete(client, tools=TOOLS)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


def test_reject_unsupported_tool_call_type(
    client,
    sdk_client,
):
    response = make_response(
        content=None,
        tool_calls=[make_tool_call()],
        finish_reason="tool_calls",
    )

    response.choices[0].message.tool_calls[0].type = "unsupported"

    sdk_client.chat.completions.create.return_value = response

    with pytest.raises(
        LLMClientError,
        match="unsupported tool-call type",
    ) as captured:
        complete(client, tools=TOOLS)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


@pytest.mark.parametrize(
    "arguments",
    [
        "not JSON",
        "{",
        "[]",
        "null",
    ],
)
def test_preserve_raw_tool_arguments(
    client,
    sdk_client,
    arguments,
):
    """JSON validation belongs to the agent dispatch boundary."""

    sdk_client.chat.completions.create.return_value = make_response(
        content=None,
        tool_calls=[
            make_tool_call(arguments=arguments),
        ],
        finish_reason="tool_calls",
    )

    result = complete(client, tools=TOOLS)

    assert result.tool_calls[0].arguments == arguments


@pytest.mark.parametrize(
    "choice_count",
    [0, 2, 3],
)
def test_reject_unexpected_choice_count(
    client,
    sdk_client,
    choice_count,
):
    response = make_response()

    response.choices = response.choices * choice_count

    sdk_client.chat.completions.create.return_value = response

    with pytest.raises(
        LLMClientError,
        match="unexpected number of choices",
    ) as captured:
        complete(client)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


@pytest.mark.parametrize(
    "finish_reason",
    [
        "stop",
        "length",
        "content_filter",
        "tool_calls",
    ],
)
def test_preserve_finish_reason(
    client,
    sdk_client,
    finish_reason,
):
    sdk_client.chat.completions.create.return_value = make_response(
        finish_reason=finish_reason,
    )

    result = complete(client)

    assert result.finish_reason == finish_reason


def test_missing_token_usage(
    client,
    sdk_client,
):
    sdk_client.chat.completions.create.return_value = make_response(usage=None)

    result = complete(client)

    assert result.usage is None


@pytest.mark.parametrize(
    ("prompt", "completion", "total"),
    [
        (0, 0, 0),
        (100, 25, 125),
        (100, 25, 150),
        (2000, 512, 2512),
    ],
)
def test_accept_valid_token_usage(
    client,
    sdk_client,
    prompt,
    completion,
    total,
):
    sdk_client.chat.completions.create.return_value = make_response(
        usage=make_usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )
    )

    result = complete(client)

    assert result.usage == TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


@pytest.mark.parametrize(
    ("prompt", "completion", "total"),
    [
        (-1, 25, 125),
        (100, -1, 125),
        (100, 25, -1),
    ],
)
def test_reject_negative_token_usage(
    client,
    sdk_client,
    prompt,
    completion,
    total,
):
    sdk_client.chat.completions.create.return_value = make_response(
        usage=make_usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )
    )

    with pytest.raises(
        LLMClientError,
        match="invalid token usage",
    ) as captured:
        complete(client)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "100",
        100.0,
        None,
    ],
)
def test_reject_non_integer_token_usage(
    client,
    sdk_client,
    value,
):
    usage = make_usage()

    # Bypass SDK coercion to test the client's own validation.
    usage.prompt_tokens = value

    sdk_client.chat.completions.create.return_value = make_response(usage=usage)

    with pytest.raises(
        LLMClientError,
        match="invalid token usage",
    ) as captured:
        complete(client)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


@pytest.mark.parametrize(
    "total",
    [0, 99, 124],
)
def test_reject_inconsistent_token_usage(
    client,
    sdk_client,
    total,
):
    sdk_client.chat.completions.create.return_value = make_response(
        usage=make_usage(
            prompt_tokens=100,
            completion_tokens=25,
            total_tokens=total,
        )
    )

    with pytest.raises(
        LLMClientError,
        match="inconsistent token usage",
    ) as captured:
        complete(client)

    assert captured.value.category == "invalid_response"
    assert captured.value.http_status is None


@pytest.mark.parametrize(
    ("status_code", "exception_type", "expected"),
    [
        (
            401,
            AuthenticationError,
            "LLM authentication failed. Check the API key.",
        ),
        (
            429,
            RateLimitError,
            "LLM rate limit or provider quota exceeded.",
        ),
        (
            400,
            APIStatusError,
            "LLM provider returned HTTP 400.",
        ),
        (
            403,
            APIStatusError,
            "LLM provider returned HTTP 403.",
        ),
        (
            404,
            APIStatusError,
            "LLM provider returned HTTP 404.",
        ),
        (
            500,
            APIStatusError,
            "LLM provider returned HTTP 500.",
        ),
        (
            503,
            APIStatusError,
            "LLM provider returned HTTP 503.",
        ),
    ],
)
def test_provider_http_errors_are_sanitized(
    client,
    sdk_client,
    status_code,
    exception_type,
    expected,
):
    sensitive_message = "synthetic-private-credential"

    request = httpx2.Request(
        "POST",
        "https://example.invalid/v1/chat/completions",
    )

    response = httpx2.Response(
        status_code,
        request=request,
    )

    sdk_client.chat.completions.create.side_effect = exception_type(
        sensitive_message,
        response=response,
        body={"error": sensitive_message},
    )

    with pytest.raises(LLMClientError) as captured:
        complete(client)

    assert str(captured.value) == expected
    assert sensitive_message not in str(captured.value)

    expected_category = {
        401: "authentication_error",
        429: "rate_limit_error",
    }.get(status_code, "provider_http_error")

    assert captured.value.category == expected_category
    assert captured.value.http_status == status_code

    sdk_client.chat.completions.create.assert_awaited_once()


def test_connection_error_is_sanitized(
    client,
    sdk_client,
):
    request = httpx2.Request(
        "POST",
        "https://example.invalid/v1/chat/completions",
    )

    sdk_client.chat.completions.create.side_effect = APIConnectionError(
        message="synthetic-private-credential",
        request=request,
    )

    with pytest.raises(LLMClientError) as captured:
        complete(client)

    assert str(captured.value) == ("Unable to connect to the LLM provider.")
    assert captured.value.category == "connection_error"
    assert captured.value.http_status is None

    sdk_client.chat.completions.create.assert_awaited_once()


def test_timeout_error_is_sanitized(
    client,
    sdk_client,
):
    request = httpx2.Request(
        "POST",
        "https://example.invalid/v1/chat/completions",
    )

    sdk_client.chat.completions.create.side_effect = APITimeoutError(request=request)

    with pytest.raises(LLMClientError) as captured:
        complete(client)

    assert str(captured.value) == ("LLM request timed out.")
    assert captured.value.category == "request_timeout"
    assert captured.value.http_status is None

    sdk_client.chat.completions.create.assert_awaited_once()


def test_client_recovers_after_provider_failure(
    client,
    sdk_client,
):
    request = httpx2.Request(
        "POST",
        "https://example.invalid/v1/chat/completions",
    )

    sdk_client.chat.completions.create.side_effect = [
        APITimeoutError(request=request),
        make_response(
            content="Recovered response.",
            usage=make_usage(),
        ),
    ]

    async def exercise():
        with pytest.raises(
            LLMClientError,
            match="request timed out",
        ):
            await client.complete(MESSAGES)

        return await client.complete(MESSAGES)

    result = asyncio.run(exercise())

    assert result.content == "Recovered response."

    assert sdk_client.chat.completions.create.await_count == 2


def test_tool_free_finalization_after_tool_response(
    client,
    sdk_client,
):
    call = make_tool_call()

    call["extra_content"] = {
        "google": {
            "thought_signature": "synthetic-signature",
        },
    }

    sdk_client.chat.completions.create.side_effect = [
        make_response(
            content=None,
            tool_calls=[call],
            finish_reason="tool_calls",
            usage=make_usage(),
        ),
        make_response(
            content="Final diagnostic response.",
            usage=make_usage(
                prompt_tokens=150,
                completion_tokens=50,
                total_tokens=200,
            ),
        ),
    ]

    async def exercise():
        messages = list(MESSAGES)

        first = await client.complete(
            messages,
            tools=TOOLS,
        )

        messages.append(first.message)

        messages.append(
            {
                "role": "tool",
                "tool_call_id": "call-001",
                "content": json.dumps(
                    {
                        "success": True,
                        "payload": {
                            "logs": "assert 201 == 400",
                        },
                    }
                ),
            }
        )

        messages.append(
            {
                "role": "user",
                "content": (
                    "No additional tools are available. Return the final diagnosis."
                ),
            }
        )

        final = await client.complete(
            messages,
            tools=None,
        )

        return first, final

    first, final = asyncio.run(exercise())

    requests = sdk_client.chat.completions.create.await_args_list

    assert len(requests) == 2

    initial_request = requests[0].kwargs
    final_request = requests[1].kwargs

    assert initial_request["tools"] == TOOLS
    assert initial_request["tool_choice"] == "auto"

    assert "tools" not in final_request
    assert "tool_choice" not in final_request

    replayed_call = final_request["messages"][2]["tool_calls"][0]

    assert replayed_call["extra_content"] == {
        "google": {
            "thought_signature": "synthetic-signature",
        },
    }

    assert first.usage.total_tokens == 125
    assert final.usage.total_tokens == 200

    assert final.content == "Final diagnostic response."
    assert final.tool_calls == ()
    assert final.finish_reason == "stop"


def test_llm_client_error_backward_compatibility():
    error = LLMClientError("Synthetic error.")

    assert str(error) == "Synthetic error."
    assert error.category == "unknown_error"
    assert error.http_status is None


@pytest.mark.parametrize(
    "category",
    [
        "authentication_error",
        "rate_limit_error",
        "request_timeout",
        "connection_error",
        "provider_http_error",
        "invalid_response",
        "invalid_request",
        "unknown_error",
    ],
)
def test_llm_client_error_preserves_valid_category(category):
    error = LLMClientError(
        "Synthetic error.",
        category=category,
    )

    assert error.category == category


@pytest.mark.parametrize(
    "category",
    [
        "",
        "unexpected_category",
        "synthetic-private-credential",
        "PROVIDER_HTTP_ERROR",
    ],
)
def test_llm_client_error_normalizes_unknown_category(category):
    error = LLMClientError(
        "Synthetic error.",
        category=category,
    )

    assert error.category == "unknown_error"


@pytest.mark.parametrize(
    "status_code",
    [100, 200, 400, 401, 429, 500, 503, 599],
)
def test_llm_client_error_preserves_valid_http_status(status_code):
    error = LLMClientError(
        "Synthetic error.",
        category="provider_http_error",
        http_status=status_code,
    )

    assert error.http_status == status_code


@pytest.mark.parametrize(
    "status_code",
    [
        None,
        -1,
        0,
        99,
        600,
        1000,
        True,
        False,
        "503",
        503.0,
    ],
)
def test_llm_client_error_normalizes_invalid_http_status(status_code):
    error = LLMClientError(
        "Synthetic error.",
        category="provider_http_error",
        http_status=status_code,
    )

    assert error.http_status is None
