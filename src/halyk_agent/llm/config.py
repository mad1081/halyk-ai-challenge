from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import re


SUPPORTED_PROVIDERS = ("openai", "anthropic")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LlmConfigurationError(ValueError):
    """Raised when no usable LLM provider can be selected."""


def read_dotenv(path: Path) -> dict[str, str]:
    """Read the dotenv syntax needed by this project.

    Blank lines and comment lines are ignored. Values may be quoted and an
    optional ``export`` prefix is accepted. Existing process variables are
    applied later and therefore take precedence over this file.
    """

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise LlmConfigurationError(
                f"Invalid dotenv line {line_number} in {path}: expected NAME=value"
            )
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not _ENV_NAME.fullmatch(name):
            raise LlmConfigurationError(
                f"Invalid environment variable name on line {line_number} in {path}"
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    name: str
    api_key: str = field(repr=False)
    model: str
    base_url: str
    timeout_seconds: float
    max_output_tokens: int
    reasoning_effort: str | None = None
    api_version: str | None = None


@dataclass(frozen=True, slots=True)
class LlmSettings:
    requested_provider: str
    priority: tuple[str, ...]
    providers: Mapping[str, ProviderSettings]
    env_file: Path

    @classmethod
    def from_env(
        cls,
        env_file: Path | str = Path(".env"),
        environ: Mapping[str, str] | None = None,
    ) -> LlmSettings:
        path = Path(env_file)
        merged = read_dotenv(path)
        # Real environment variables intentionally override local .env values.
        merged.update(dict(os.environ if environ is None else environ))

        requested = merged.get("HALYK_LLM_PROVIDER", "auto").strip().lower()
        if requested not in ("auto", *SUPPORTED_PROVIDERS):
            choices = ", ".join(("auto", *SUPPORTED_PROVIDERS))
            raise LlmConfigurationError(
                f"HALYK_LLM_PROVIDER must be one of: {choices}"
            )

        priority = _parse_priority(
            merged.get("HALYK_LLM_PRIORITY", "openai,anthropic")
        )
        timeout = _positive_float(
            merged.get("HALYK_LLM_TIMEOUT_SECONDS", "180"),
            "HALYK_LLM_TIMEOUT_SECONDS",
        )
        max_tokens = _positive_int(
            merged.get("HALYK_LLM_MAX_OUTPUT_TOKENS", "8192"),
            "HALYK_LLM_MAX_OUTPUT_TOKENS",
        )

        providers: dict[str, ProviderSettings] = {}
        openai_key = merged.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            providers["openai"] = ProviderSettings(
                name="openai",
                api_key=openai_key,
                model=merged.get("OPENAI_MODEL", "gpt-5.6-sol").strip()
                or "gpt-5.6-sol",
                base_url=merged.get(
                    "OPENAI_BASE_URL", "https://api.openai.com/v1"
                ).strip().rstrip("/"),
                timeout_seconds=timeout,
                max_output_tokens=max_tokens,
                reasoning_effort=(
                    merged.get("OPENAI_REASONING_EFFORT", "high").strip() or None
                ),
            )

        anthropic_key = merged.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            providers["anthropic"] = ProviderSettings(
                name="anthropic",
                api_key=anthropic_key,
                model=merged.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip()
                or "claude-sonnet-5",
                base_url=merged.get(
                    "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
                ).strip().rstrip("/"),
                timeout_seconds=timeout,
                max_output_tokens=max_tokens,
                api_version=merged.get(
                    "ANTHROPIC_API_VERSION", "2023-06-01"
                ).strip()
                or "2023-06-01",
            )

        return cls(
            requested_provider=requested,
            priority=priority,
            providers=providers,
            env_file=path,
        )

    @property
    def available_providers(self) -> tuple[str, ...]:
        return tuple(name for name in SUPPORTED_PROVIDERS if name in self.providers)

    def select(self) -> ProviderSettings:
        if self.requested_provider != "auto":
            selected = self.providers.get(self.requested_provider)
            if selected is None:
                variable = (
                    "OPENAI_API_KEY"
                    if self.requested_provider == "openai"
                    else "ANTHROPIC_API_KEY"
                )
                raise LlmConfigurationError(
                    f"Provider {self.requested_provider!r} was requested, but {variable} is empty"
                )
            return selected

        for provider_name in self.priority:
            selected = self.providers.get(provider_name)
            if selected is not None:
                return selected
        raise LlmConfigurationError(
            "No LLM credentials found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY "
            f"in {self.env_file} or in the process environment."
        )

    def public_summary(self) -> dict[str, object]:
        selected = self.select()
        return {
            "env_file": str(self.env_file),
            "requested_provider": self.requested_provider,
            "priority": list(self.priority),
            "available_providers": list(self.available_providers),
            "selected_provider": selected.name,
            "model": selected.model,
            "base_url": selected.base_url,
            "api_key_present": True,
        }


def _parse_priority(value: str) -> tuple[str, ...]:
    names = tuple(name.strip().lower() for name in value.split(",") if name.strip())
    if not names or set(names) != set(SUPPORTED_PROVIDERS) or len(names) != len(
        SUPPORTED_PROVIDERS
    ):
        raise LlmConfigurationError(
            "HALYK_LLM_PRIORITY must list openai and anthropic exactly once"
        )
    return names


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise LlmConfigurationError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise LlmConfigurationError(f"{name} must be positive")
    return parsed


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise LlmConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise LlmConfigurationError(f"{name} must be positive")
    return parsed
