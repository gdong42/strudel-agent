from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .base import ProviderError


REQUEST_TIMEOUT_SECONDS = 45.0
DEBUG_PAYLOAD_CHAR_LIMIT = 100_000
DEBUG_STREAM_PAYLOAD_CHAR_LIMIT = 16_000
_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
    }
)
_DEBUG_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(api[-_ ]?key|authorization|access[-_ ]?token|refresh[-_ ]?token|client[-_ ]?secret)"
    r"([\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?([^,\s;\"']+)"
)
_DEBUG_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^,\s;]+")
_DEBUG_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
logger = logging.getLogger("uvicorn.error.strudel_agent.provider_http")


@dataclass
class _DebugStreamCapture:
    fragments: list[str] = field(default_factory=list)
    total_chars: int = 0
    captured_chars: int = 0
    truncated: bool = False

    def add(self, serialized: str) -> None:
        separator_chars = 1 if self.total_chars > 0 else 0
        self.total_chars += separator_chars + len(serialized)
        remaining = DEBUG_STREAM_PAYLOAD_CHAR_LIMIT - self.captured_chars
        if remaining <= separator_chars:
            self.truncated = True
            return
        fragment = serialized[: remaining - separator_chars]
        self.fragments.append(fragment)
        self.captured_chars += separator_chars + len(fragment)
        if len(fragment) < len(serialized):
            self.truncated = True

    def payload(self) -> str:
        suffix = ",...[truncated]" if self.truncated else ""
        return f"[{','.join(self.fragments)}{suffix}]"


class ProviderHttpClient:
    def __init__(
        self,
        provider_label: str,
        api_key: str,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_label = provider_label
        self.api_key = api_key
        self.base_url = base_url
        self.transport = transport

    async def request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        method = method.upper()
        log_path = self._log_path(path)
        started_at = time.monotonic()
        logger.info(
            "Provider HTTP request started provider=%s method=%s path=%s stream=false",
            self.provider_label,
            method,
            log_path,
        )
        self._log_debug_payload("Provider HTTP request payload", method, log_path, kwargs.get("json"))
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            self._log_transport_failure(method, log_path, started_at, "timeout")
            raise ProviderError(f"{self.provider_label} request timed out", retryable=True) from error
        except httpx.RequestError as error:
            self._log_transport_failure(method, log_path, started_at, type(error).__name__)
            raise ProviderError(f"{self.provider_label} is unavailable", retryable=True) from error

        logger.info(
            "Provider HTTP response received provider=%s method=%s path=%s status=%s stream=false duration_ms=%s",
            self.provider_label,
            method,
            log_path,
            response.status_code,
            self._elapsed_milliseconds(started_at),
        )
        if response.is_error:
            self._log_debug_payload(
                "Provider HTTP response body",
                method,
                log_path,
                self._debug_response_body(response),
            )
            raise self._response_error(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError(f"{self.provider_label} returned an invalid response") from error
        self._log_debug_payload("Provider HTTP response body", method, log_path, payload)
        return payload

    async def stream_sse_json(self, method: str, path: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        method = method.upper()
        log_path = self._log_path(path)
        started_at = time.monotonic()
        response_status: int | None = None
        event_count = 0
        completed = False
        debug_capture = _DebugStreamCapture() if logger.isEnabledFor(logging.DEBUG) else None
        logger.info(
            "Provider HTTP request started provider=%s method=%s path=%s stream=true",
            self.provider_label,
            method,
            log_path,
        )
        self._log_debug_payload("Provider HTTP request payload", method, log_path, kwargs.get("json"))
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                transport=self.transport,
            ) as client:
                async with client.stream(method, path, **kwargs) as response:
                    response_status = response.status_code
                    logger.info(
                        "Provider HTTP response received provider=%s method=%s path=%s status=%s stream=true duration_ms=%s",
                        self.provider_label,
                        method,
                        log_path,
                        response.status_code,
                        self._elapsed_milliseconds(started_at),
                    )
                    if response.is_error:
                        await response.aread()
                        self._log_debug_payload(
                            "Provider HTTP response body",
                            method,
                            log_path,
                            self._debug_response_body(response),
                        )
                        raise self._response_error(response)
                    async for line in response.aiter_lines():
                        stripped = line.strip()
                        if not stripped or stripped.startswith(":") or not stripped.startswith("data:"):
                            continue
                        data = stripped[5:].strip()
                        if data == "[DONE]":
                            completed = True
                            return
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError as error:
                            raise ProviderError(f"{self.provider_label} returned an invalid stream") from error
                        if not isinstance(event, dict):
                            raise ProviderError(f"{self.provider_label} returned an invalid stream")
                        event_count += 1
                        if debug_capture is not None:
                            debug_capture.add(self._serialize_debug_payload(event))
                        yield event
        except ProviderError:
            raise
        except httpx.TimeoutException as error:
            self._log_transport_failure(method, log_path, started_at, "timeout", stream=True)
            raise ProviderError(f"{self.provider_label} request timed out", retryable=True) from error
        except httpx.RequestError as error:
            self._log_transport_failure(method, log_path, started_at, type(error).__name__, stream=True)
            raise ProviderError(f"{self.provider_label} is unavailable", retryable=True) from error
        finally:
            if debug_capture is not None:
                logger.debug(
                    "Provider HTTP stream payload provider=%s method=%s path=%s completed=%s "
                    "events=%s chars=%s captured_chars=%s truncated=%s payload=%s",
                    self.provider_label,
                    method,
                    log_path,
                    str(completed).lower(),
                    event_count,
                    debug_capture.total_chars,
                    debug_capture.captured_chars,
                    str(debug_capture.truncated).lower(),
                    debug_capture.payload(),
                )
            if response_status is not None and response_status < 400:
                logger.info(
                    "Provider HTTP stream closed provider=%s method=%s path=%s status=%s completed=%s events=%s duration_ms=%s",
                    self.provider_label,
                    method,
                    log_path,
                    response_status,
                    str(completed).lower(),
                    event_count,
                    self._elapsed_milliseconds(started_at),
                )

    def _response_error(self, response: httpx.Response) -> ProviderError:
        if response.status_code in (401, 403):
            return ProviderError(f"{self.provider_label} rejected the API key")
        if response.status_code == 429:
            return ProviderError(f"{self.provider_label} rate limit reached", retryable=True)
        if response.status_code >= 500:
            return ProviderError(f"{self.provider_label} is unavailable", retryable=True)
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = None
        return ProviderError(message or f"{self.provider_label} request failed ({response.status_code})")

    def _log_transport_failure(
        self,
        method: str,
        path: str,
        started_at: float,
        error: str,
        *,
        stream: bool = False,
    ) -> None:
        logger.warning(
            "Provider HTTP request failed provider=%s method=%s path=%s stream=%s error=%s duration_ms=%s",
            self.provider_label,
            method,
            path,
            str(stream).lower(),
            error,
            self._elapsed_milliseconds(started_at),
        )

    def _log_debug_payload(
        self,
        event: str,
        method: str,
        path: str,
        payload: object,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        serialized = self._serialize_debug_payload(payload)
        original_length = len(serialized)
        truncated = original_length > DEBUG_PAYLOAD_CHAR_LIMIT
        if truncated:
            serialized = f"{serialized[:DEBUG_PAYLOAD_CHAR_LIMIT]}...[truncated]"
        logger.debug(
            "%s provider=%s method=%s path=%s chars=%s truncated=%s payload=%s",
            event,
            self.provider_label,
            method,
            path,
            original_length,
            str(truncated).lower(),
            serialized,
        )

    def _serialize_debug_payload(self, payload: object) -> str:
        return json.dumps(
            self._redact_debug_value(payload),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _redact_debug_value(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): (
                    "[REDACTED]"
                    if re.sub(r"[^a-z]", "", str(key).lower()) in _SENSITIVE_PAYLOAD_KEYS
                    else cls._redact_debug_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._redact_debug_value(item) for item in value]
        if isinstance(value, str):
            redacted = _DEBUG_CREDENTIAL_PATTERN.sub(
                lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
                value,
            )
            redacted = _DEBUG_BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
            return _DEBUG_API_KEY_PATTERN.sub("[REDACTED]", redacted)
        return value

    @staticmethod
    def _debug_response_body(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def _log_path(path: str) -> str:
        normalized = "/" + path.lstrip("/").split("?", 1)[0]
        return normalized[:200]

    @staticmethod
    def _elapsed_milliseconds(started_at: float) -> int:
        return max(0, round((time.monotonic() - started_at) * 1000))
