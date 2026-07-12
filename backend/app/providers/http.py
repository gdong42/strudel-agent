from __future__ import annotations

from typing import Any

import httpx

from .base import ProviderError


REQUEST_TIMEOUT_SECONDS = 45.0


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
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            raise ProviderError(f"{self.provider_label} request timed out", retryable=True) from error
        except httpx.RequestError as error:
            raise ProviderError(f"{self.provider_label} is unavailable", retryable=True) from error

        if response.is_error:
            raise self._response_error(response)
        try:
            return response.json()
        except ValueError as error:
            raise ProviderError(f"{self.provider_label} returned an invalid response") from error

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
