from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from typing import Any

from halyk_agent.llm import (
    AnthropicProvider,
    LlmConfigurationError,
    LlmSettings,
    OpenAIProvider,
    build_provider,
    read_dotenv,
)


SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}},
    "required": ["verdict"],
    "additionalProperties": False,
}


class FakeTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout": timeout,
            }
        )
        return self.response


class LlmConfigurationTests(unittest.TestCase):
    def test_dotenv_reader_supports_quotes_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text(
                "# comment\nexport OPENAI_API_KEY='openai-secret'\n"
                'ANTHROPIC_API_KEY="anthropic-secret"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                read_dotenv(path),
                {
                    "OPENAI_API_KEY": "openai-secret",
                    "ANTHROPIC_API_KEY": "anthropic-secret",
                },
            )

    def test_auto_selects_only_available_openai_key(self) -> None:
        settings = LlmSettings.from_env(
            "missing.env", environ={"OPENAI_API_KEY": "secret"}
        )
        self.assertEqual(settings.select().name, "openai")

    def test_auto_selects_only_available_anthropic_key(self) -> None:
        settings = LlmSettings.from_env(
            "missing.env", environ={"ANTHROPIC_API_KEY": "secret"}
        )
        self.assertEqual(settings.select().name, "anthropic")

    def test_priority_decides_when_both_keys_exist(self) -> None:
        settings = LlmSettings.from_env(
            "missing.env",
            environ={
                "OPENAI_API_KEY": "openai-secret",
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "HALYK_LLM_PRIORITY": "anthropic,openai",
            },
        )
        self.assertEqual(settings.select().name, "anthropic")

    def test_process_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("OPENAI_MODEL=from-file\n", encoding="utf-8")
            settings = LlmSettings.from_env(
                path,
                environ={
                    "OPENAI_API_KEY": "secret",
                    "OPENAI_MODEL": "from-process",
                },
            )
            self.assertEqual(settings.select().model, "from-process")

    def test_forced_provider_requires_its_own_key(self) -> None:
        settings = LlmSettings.from_env(
            "missing.env",
            environ={
                "HALYK_LLM_PROVIDER": "openai",
                "ANTHROPIC_API_KEY": "secret",
            },
        )
        with self.assertRaisesRegex(LlmConfigurationError, "OPENAI_API_KEY"):
            settings.select()

    def test_no_keys_is_a_clear_error(self) -> None:
        settings = LlmSettings.from_env("missing.env", environ={})
        with self.assertRaisesRegex(LlmConfigurationError, "OPENAI_API_KEY"):
            settings.select()

    def test_settings_repr_does_not_reveal_key(self) -> None:
        settings = LlmSettings.from_env(
            "missing.env", environ={"OPENAI_API_KEY": "do-not-print-this"}
        )
        self.assertNotIn("do-not-print-this", repr(settings))


class ProviderRequestTests(unittest.TestCase):
    def test_openai_uses_responses_api_and_strict_json_schema(self) -> None:
        transport = FakeTransport(
            {
                "id": "resp_test",
                "model": "gpt-test",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"verdict":"BREACH"}'}
                        ],
                    }
                ],
                "usage": {"total_tokens": 42},
            }
        )
        settings = LlmSettings.from_env(
            "missing.env",
            environ={"OPENAI_API_KEY": "openai-secret", "OPENAI_MODEL": "gpt-test"},
        )
        provider = build_provider(settings, transport)
        self.assertIsInstance(provider, OpenAIProvider)

        result = provider.generate_json(
            system_prompt="Decide a covenant.",
            user_prompt="Evidence here.",
            schema=SCHEMA,
            schema_name="covenant_decision",
        )

        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(call["headers"]["Authorization"], "Bearer openai-secret")
        self.assertEqual(call["payload"]["text"]["format"]["type"], "json_schema")
        self.assertTrue(call["payload"]["text"]["format"]["strict"])
        self.assertFalse(call["payload"]["store"])
        self.assertEqual(result.value, {"verdict": "BREACH"})

    def test_anthropic_uses_messages_api_and_structured_output(self) -> None:
        transport = FakeTransport(
            {
                "id": "msg_test",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"verdict":"COMPLIANT"}'}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        )
        settings = LlmSettings.from_env(
            "missing.env",
            environ={
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "ANTHROPIC_MODEL": "claude-test",
            },
        )
        provider = build_provider(settings, transport)
        self.assertIsInstance(provider, AnthropicProvider)

        result = provider.generate_json(
            system_prompt="Decide a covenant.",
            user_prompt="Evidence here.",
            schema=SCHEMA,
            schema_name="covenant_decision",
        )

        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(call["headers"]["x-api-key"], "anthropic-secret")
        self.assertEqual(call["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(
            call["payload"]["output_config"]["format"]["type"], "json_schema"
        )
        self.assertEqual(result.value, {"verdict": "COMPLIANT"})


if __name__ == "__main__":
    unittest.main()
