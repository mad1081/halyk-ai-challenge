from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Protocol

from halyk_agent.llm.config import LlmSettings, ProviderSettings
from halyk_agent.llm.transport import JsonTransport, TransportError, UrllibJsonTransport


_SCHEMA_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LlmApiError(RuntimeError):
    """Raised for a provider error or an unusable model response."""


@dataclass(frozen=True, slots=True)
class LlmResult:
    provider: str
    model: str
    value: dict[str, Any]
    usage: dict[str, Any]
    response_id: str | None


class StructuredLlm(Protocol):
    settings: ProviderSettings

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> LlmResult: ...


class OpenAIProvider:
    def __init__(
        self,
        settings: ProviderSettings,
        transport: JsonTransport | None = None,
    ) -> None:
        if settings.name != "openai":
            raise ValueError("OpenAIProvider requires OpenAI settings")
        self.settings = settings
        self.transport = transport or UrllibJsonTransport()

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> LlmResult:
        _validate_request(system_prompt, user_prompt, schema, schema_name)
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
            "max_output_tokens": self.settings.max_output_tokens,
            # Challenge documents are banking data; do not opt into response storage.
            "store": False,
        }
        if self.settings.reasoning_effort:
            payload["reasoning"] = {"effort": self.settings.reasoning_effort}

        response = self._post(
            f"{self.settings.base_url}/responses",
            {
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        status = response.get("status")
        if status != "completed":
            detail = response.get("incomplete_details") or response.get("error") or status
            raise LlmApiError(f"OpenAI response was not completed: {detail}")

        text = _openai_output_text(response)
        return LlmResult(
            provider="openai",
            model=str(response.get("model") or self.settings.model),
            value=_decode_json_object(text, "OpenAI"),
            usage=_dict_or_empty(response.get("usage")),
            response_id=_optional_string(response.get("id")),
        )

    def _post(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return self.transport.post_json(
                url, headers, payload, self.settings.timeout_seconds
            )
        except TransportError as exc:
            raise LlmApiError(_redact_secret(str(exc), self.settings.api_key)) from exc


class AnthropicProvider:
    def __init__(
        self,
        settings: ProviderSettings,
        transport: JsonTransport | None = None,
    ) -> None:
        if settings.name != "anthropic":
            raise ValueError("AnthropicProvider requires Anthropic settings")
        self.settings = settings
        self.transport = transport or UrllibJsonTransport()

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> LlmResult:
        _validate_request(system_prompt, user_prompt, schema, schema_name)
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": schema,
                }
            },
        }
        response = self._post(
            _anthropic_messages_url(self.settings.base_url),
            {
                "x-api-key": self.settings.api_key,
                "anthropic-version": self.settings.api_version or "2023-06-01",
                "content-type": "application/json",
            },
            payload,
        )
        stop_reason = response.get("stop_reason")
        if stop_reason in {"refusal", "max_tokens"}:
            raise LlmApiError(f"Anthropic response stopped with reason: {stop_reason}")

        text = _anthropic_output_text(response)
        return LlmResult(
            provider="anthropic",
            model=str(response.get("model") or self.settings.model),
            value=_decode_json_object(text, "Anthropic"),
            usage=_dict_or_empty(response.get("usage")),
            response_id=_optional_string(response.get("id")),
        )

    def _post(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return self.transport.post_json(
                url, headers, payload, self.settings.timeout_seconds
            )
        except TransportError as exc:
            raise LlmApiError(_redact_secret(str(exc), self.settings.api_key)) from exc


def build_provider(
    settings: LlmSettings,
    transport: JsonTransport | None = None,
) -> StructuredLlm:
    selected = settings.select()
    if selected.name == "openai":
        return OpenAIProvider(selected, transport)
    if selected.name == "anthropic":
        return AnthropicProvider(selected, transport)
    raise AssertionError(f"Unsupported provider selected: {selected.name}")


def build_provider_from_env(
    env_file: Path | str = Path(".env"),
    *,
    transport: JsonTransport | None = None,
) -> StructuredLlm:
    return build_provider(LlmSettings.from_env(env_file), transport)


def _validate_request(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    schema_name: str,
) -> None:
    if not system_prompt.strip():
        raise ValueError("system_prompt must not be empty")
    if not user_prompt.strip():
        raise ValueError("user_prompt must not be empty")
    if schema.get("type") != "object":
        raise ValueError("structured output schema must have object at its root")
    if not _SCHEMA_NAME.fullmatch(schema_name):
        raise ValueError(
            "schema_name must contain 1-64 letters, digits, underscores, or hyphens"
        )


def _openai_output_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise LlmApiError("OpenAI refused the structured-output request")
            if content.get("type") == "output_text" and isinstance(
                content.get("text"), str
            ):
                return content["text"]
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    raise LlmApiError("OpenAI response did not contain output_text")


def _anthropic_output_text(response: dict[str, Any]) -> str:
    for content in response.get("content", []):
        if (
            isinstance(content, dict)
            and content.get("type") == "text"
            and isinstance(content.get("text"), str)
        ):
            return content["text"]
    raise LlmApiError("Anthropic response did not contain a text block")


def _decode_json_object(text: str, provider: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmApiError(f"{provider} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LlmApiError(f"{provider} returned JSON that is not an object")
    return value


def _anthropic_messages_url(base_url: str) -> str:
    suffix = "/messages" if base_url.endswith("/v1") else "/v1/messages"
    return f"{base_url}{suffix}"


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _redact_secret(message: str, secret: str) -> str:
    return message.replace(secret, "[REDACTED]") if secret else message
