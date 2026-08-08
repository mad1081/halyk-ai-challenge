from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TransportError(RuntimeError):
    """A sanitized HTTP transport failure that never includes request headers."""


class JsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> dict[str, Any]: ...


class UrllibJsonTransport:
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        request = Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _safe_response_detail(exc.read())
            raise TransportError(
                f"API request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise TransportError(f"API request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TransportError(f"API request timed out after {timeout:g}s") from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TransportError("API returned a non-JSON response") from exc
        if not isinstance(decoded, dict):
            raise TransportError("API returned a JSON value that is not an object")
        return decoded


def _safe_response_detail(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")[:1000]
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return text.strip() or "empty response body"
    if isinstance(decoded, dict):
        error = decoded.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:500]
        if isinstance(error, str):
            return error[:500]
    return "API returned an error response"
