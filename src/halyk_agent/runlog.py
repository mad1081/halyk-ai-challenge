from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any

from halyk_agent.llm.transport import JsonTransport


class JsonlRunLogger:
    """Append-only event log plus readable per-step JSON artifacts."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self._sequence = 0
        self._request_sequence = 0
        self._lock = Lock()

    def event(self, event_type: str, **data: Any) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            record = {
                "sequence": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event_type,
                **data,
            }
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=_json_default))
                handle.write("\n")
        return record

    def next_request_id(self) -> str:
        with self._lock:
            self._request_sequence += 1
            return f"{self._request_sequence:04d}"

    def artifact(self, relative_path: Path | str, value: Any) -> Path:
        with self._lock:
            # Resolve and create under the same lock. On Windows, concurrent
            # resolution while another thread creates the parent can produce
            # inconsistent extended-path (\\?\) forms.
            path = (self.run_dir / relative_path).resolve()
            try:
                path.relative_to(self.run_dir)
            except ValueError as exc:
                raise ValueError(
                    f"Artifact path escapes run directory: {relative_path}"
                ) from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp")
            if isinstance(value, str):
                text = value
            else:
                text = json.dumps(
                    value,
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                )
            temporary.write_text(
                text.rstrip() + "\n", encoding="utf-8", newline="\n"
            )
            temporary.replace(path)
        return path


class RecordingTransport:
    """Record full JSON requests/responses while removing credentials."""

    def __init__(
        self,
        inner: JsonTransport,
        logger: JsonlRunLogger,
        provider: str,
    ) -> None:
        self.inner = inner
        self.logger = logger
        self.provider = provider
        self.context: dict[str, Any] = {}

    def set_context(self, **context: Any) -> None:
        self.context = dict(context)

    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        request_id = self.logger.next_request_id()
        started_at = datetime.now(timezone.utc).isoformat()
        request_record = {
            "request_id": request_id,
            "provider": self.provider,
            "context": self.context,
            "method": "POST",
            "url": url,
            "headers": _redact_headers(headers),
            "timeout_seconds": timeout,
            "started_at": started_at,
            "body": payload,
        }
        request_path = self.logger.artifact(
            Path("api") / f"{request_id}-request.json", request_record
        )
        self.logger.event(
            "api_request",
            provider=self.provider,
            request_id=request_id,
            context=self.context,
            artifact=str(request_path.relative_to(self.logger.run_dir)),
        )

        started = time.perf_counter()
        try:
            response = self.inner.post_json(url, headers, payload, timeout)
        except Exception as exc:
            elapsed = round(time.perf_counter() - started, 4)
            safe_error = _redact_text(str(exc), headers)
            error_record = {
                "request_id": request_id,
                "provider": self.provider,
                "context": self.context,
                "elapsed_seconds": elapsed,
                "elapsed_minutes": round(elapsed / 60, 4),
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error": safe_error,
            }
            error_path = self.logger.artifact(
                Path("api") / f"{request_id}-error.json", error_record
            )
            self.logger.event(
                "api_error",
                provider=self.provider,
                request_id=request_id,
                context=self.context,
                elapsed_seconds=elapsed,
                elapsed_minutes=round(elapsed / 60, 4),
                artifact=str(error_path.relative_to(self.logger.run_dir)),
            )
            raise

        elapsed = round(time.perf_counter() - started, 4)
        response_record = {
            "request_id": request_id,
            "provider": self.provider,
            "context": self.context,
            "elapsed_seconds": elapsed,
            "elapsed_minutes": round(elapsed / 60, 4),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "body": response,
        }
        response_path = self.logger.artifact(
            Path("api") / f"{request_id}-response.json", response_record
        )
        self.logger.event(
            "api_response",
            provider=self.provider,
            request_id=request_id,
            context=self.context,
            elapsed_seconds=elapsed,
            elapsed_minutes=round(elapsed / 60, 4),
            response_id=response.get("id"),
            artifact=str(response_path.relative_to(self.logger.run_dir)),
        )
        return response


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        normalized = name.lower()
        if any(marker in normalized for marker in ("authorization", "api-key", "token")):
            result[name] = "[REDACTED]"
        else:
            result[name] = value
    return result


def _redact_text(text: str, headers: Mapping[str, str]) -> str:
    for name, value in headers.items():
        normalized = name.lower()
        if any(marker in normalized for marker in ("authorization", "api-key", "token")):
            if value:
                text = text.replace(value, "[REDACTED]")
            if normalized == "authorization" and value.lower().startswith("bearer "):
                text = text.replace(value[7:], "[REDACTED]")
    return text


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__} to JSON")
