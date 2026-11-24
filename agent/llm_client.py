"""Asynchronous LLM client with Gemini-compatible tool calling."""

from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from agent.config import AgentSettings


class LLMClientError(RuntimeError):
    """A controlled LLM communication or response error."""

    ALLOWED_CATEGORIES = frozenset(
        {
            "authentication_error",
            "rate_limit_error",
            "request_timeout",
            "connection_error",
            "provider_http_error",
            "invalid_response",
            "invalid_request",
            "unknown_error",
        }
    )

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown_error",
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)

        self.category = (
            category if category in self.ALLOWED_CATEGORIES else "unknown_error"
        )

        self.http_status = (
            http_status
            if type(http_status) is int and 100 <= http_status <= 599
            else None
        )


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-reported token consumption."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class RequestedToolCall:
    """A tool invocation requested by the model."""

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized response from the configured LLM."""

    message: dict[str, Any]
    content: str | None
    tool_calls: tuple[RequestedToolCall, ...]
    finish_reason: str
    usage: TokenUsage | None


class DiagnosticLLMClient:
    """Communicate with an OpenAI-compatible LLM endpoint."""

    def __init__(
        self,
        settings: AgentSettings,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._settings = settings

        self._owns_client = client is None

        self._client = (
            client
            if client is not None
            else AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=float(settings.llm_timeout),
                max_retries=0,
            )
        )

    async def __aenter__(self) -> Self:
        """Enter the managed client context."""

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close owned HTTP resources."""

        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client when owned."""

        if self._owns_client:
            await self._client.close()

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Request a completion without executing model tools."""

        if not messages:
            raise LLMClientError(
                "LLM conversation must not be empty.",
                category="invalid_request",
            )

        output_limit = (
            self._settings.max_output_tokens
            if max_output_tokens is None
            else max_output_tokens
        )

        if (
            type(output_limit) is not int
            or not 1 <= output_limit <= self._settings.max_output_tokens
        ):
            raise LLMClientError(
                "Invalid LLM output token limit.",
                category="invalid_request",
            )

        request_timeout = (
            float(self._settings.llm_timeout)
            if timeout_seconds is None
            else timeout_seconds
        )

        if not 0 < request_timeout <= self._settings.llm_timeout:
            raise LLMClientError(
                "Invalid LLM request timeout.",
                category="invalid_request",
            )

        request: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": list(messages),
            "max_tokens": output_limit,
            "timeout": request_timeout,
        }

        # Omitting tool definitions entirely is intentional.
        # Gemini previously requested additional tools when
        # tool_choice="none" was supplied during finalization.
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "auto"

        try:
            response = await self._client.chat.completions.create(**request)

        except AuthenticationError as exc:
            raise LLMClientError(
                "LLM authentication failed. Check the API key.",
                category="authentication_error",
                http_status=exc.status_code,
            ) from None

        except RateLimitError as exc:
            raise LLMClientError(
                "LLM rate limit or provider quota exceeded.",
                category="rate_limit_error",
                http_status=exc.status_code,
            ) from None

        except APITimeoutError:
            raise LLMClientError(
                "LLM request timed out.",
                category="request_timeout",
            ) from None

        except APIConnectionError:
            raise LLMClientError(
                "Unable to connect to the LLM provider.",
                category="connection_error",
            ) from None

        except APIStatusError as exc:
            raise LLMClientError(
                f"LLM provider returned HTTP {exc.status_code}.",
                category="provider_http_error",
                http_status=exc.status_code,
            ) from None

        if len(response.choices) != 1:
            raise LLMClientError(
                "LLM returned an unexpected number of choices.",
                category="invalid_response",
            )

        choice = response.choices[0]
        message = choice.message

        # Validate tool calls before serializing the assistant message.
        requested_calls = []

        for call in message.tool_calls or []:
            if call.type != "function":
                raise LLMClientError(
                    "LLM returned an unsupported tool-call type.",
                    category="invalid_response",
                )

            if (
                not call.id
                or not call.function.name
                or not isinstance(
                    call.function.arguments,
                    str,
                )
            ):
                raise LLMClientError(
                    "LLM returned a malformed tool call.",
                    category="invalid_response",
                )

            requested_calls.append(
                RequestedToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=call.function.arguments,
                )
            )

        call_ids = [call.call_id for call in requested_calls]

        if len(call_ids) != len(set(call_ids)):
            raise LLMClientError(
                "LLM returned duplicate tool-call identifiers.",
                category="invalid_response",
            )

        usage = None

        if response.usage is not None:
            reported = response.usage

            counts = (
                reported.prompt_tokens,
                reported.completion_tokens,
                reported.total_tokens,
            )

            if any(type(count) is not int or count < 0 for count in counts):
                raise LLMClientError(
                    "LLM returned invalid token usage.",
                    category="invalid_response",
                )

            if (
                reported.total_tokens
                < reported.prompt_tokens + reported.completion_tokens
            ):
                raise LLMClientError(
                    "LLM returned inconsistent token usage.",
                    category="invalid_response",
                )

            usage = TokenUsage(
                prompt_tokens=reported.prompt_tokens,
                completion_tokens=reported.completion_tokens,
                total_tokens=reported.total_tokens,
            )

        # Serialize only after tool calls and token usage are validated.
        # Preserve provider-specific metadata, including
        # Gemini thought signatures attached to tool calls.
        serialized_message = message.model_dump(
            exclude_none=True,
            mode="json",
        )

        return LLMResponse(
            message=serialized_message,
            content=message.content,
            tool_calls=tuple(requested_calls),
            finish_reason=choice.finish_reason,
            usage=usage,
        )
