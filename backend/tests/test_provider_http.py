from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.providers.http import ProviderHttpClient


PROVIDER_HTTP_LOGGER = "uvicorn.error.strudel_agent.provider_http"


@pytest.mark.anyio
async def test_json_request_logs_safe_outbound_lifecycle(caplog: pytest.LogCaptureFixture) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    client = ProviderHttpClient(
        "Test Provider",
        "header-secret",
        "https://provider.example/v1/",
        transport=transport,
    )

    with caplog.at_level(logging.INFO, logger=PROVIDER_HTTP_LOGGER):
        result = await client.request_json(
            "POST",
            "responses?private=query-secret",
            json={"input": "private prompt", "api_key": "body-secret"},
        )

    assert result == {"ok": True}
    assert (
        "Provider HTTP request started provider=Test Provider method=POST path=/responses stream=false"
        in caplog.text
    )
    assert "path=/responses status=200 stream=false duration_ms=" in caplog.text
    assert "header-secret" not in caplog.text
    assert "query-secret" not in caplog.text
    assert "body-secret" not in caplog.text
    assert "private prompt" not in caplog.text


@pytest.mark.anyio
async def test_debug_level_logs_redacted_request_and_response_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "response-1", "output": "debug model response", "api_key": "response-secret"},
        )
    )
    client = ProviderHttpClient(
        "Test Provider",
        "header-secret",
        "https://provider.example/v1/",
        transport=transport,
    )

    with caplog.at_level(logging.DEBUG, logger=PROVIDER_HTTP_LOGGER):
        await client.request_json(
            "POST",
            "responses",
            json={"input": "debug user prompt", "api_key": "request-secret"},
        )

    assert 'payload={"input":"debug user prompt","api_key":"[REDACTED]"}' in caplog.text
    assert '"output":"debug model response"' in caplog.text
    assert '"api_key":"[REDACTED]"' in caplog.text
    assert "header-secret" not in caplog.text
    assert "request-secret" not in caplog.text
    assert "response-secret" not in caplog.text


@pytest.mark.anyio
async def test_stream_request_logs_response_and_completion(caplog: pytest.LogCaptureFixture) -> None:
    body = f'data: {json.dumps({"type": "delta"})}\n\ndata: [DONE]\n\n'
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    client = ProviderHttpClient(
        "Test Provider",
        "test-key",
        "https://provider.example/v1/",
        transport=transport,
    )

    with caplog.at_level(logging.INFO, logger=PROVIDER_HTTP_LOGGER):
        events = [event async for event in client.stream_sse_json("POST", "responses")]

    assert events == [{"type": "delta"}]
    assert "path=/responses status=200 stream=true duration_ms=" in caplog.text
    assert "status=200 completed=true events=1 duration_ms=" in caplog.text
    assert '"type":"delta"' not in caplog.text


@pytest.mark.anyio
async def test_debug_level_logs_stream_events(caplog: pytest.LogCaptureFixture) -> None:
    body = f'data: {json.dumps({"type": "delta", "text": "debug stream response"})}\n\ndata: [DONE]\n\n'
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    client = ProviderHttpClient(
        "Test Provider",
        "test-key",
        "https://provider.example/v1/",
        transport=transport,
    )

    with caplog.at_level(logging.DEBUG, logger=PROVIDER_HTTP_LOGGER):
        events = [event async for event in client.stream_sse_json("POST", "responses")]

    assert events == [{"type": "delta", "text": "debug stream response"}]
    assert "Provider HTTP stream event" in caplog.text
    assert 'payload={"type":"delta","text":"debug stream response"}' in caplog.text
