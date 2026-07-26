from __future__ import annotations

import json

import httpx
import pytest

from app.models import ChangeRequest
from app.providers.base import ProviderError, ProviderRequest
from app.providers.openai import OpenAIProvider


@pytest.mark.anyio
async def test_openai_provider_sends_strict_schema_and_parses_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert payload["text"]["format"]["schema"]["additionalProperties"] is False
        assert set(payload["text"]["format"]["schema"]["required"]) == {"code", "explanation"}
        assert set(payload["text"]["format"]["schema"]["properties"]["action"]["enum"]) == {"apply", "noop"}
        assert payload["model"] == "test-model"
        assert json.loads(payload["input"])["user_intent"] == "make it groovy"
        return httpx.Response(
            200,
            json={
                "output": [{
                    "type": "message",
                    "content": [{
                        "type": "output_text",
                        "text": json.dumps({"code": 's("bd*4")', "explanation": "Added a steady kick."}),
                    }],
                }]
            },
        )

    provider = OpenAIProvider("test-key", "test-model", transport=httpx.MockTransport(handler))
    result = await provider.create_change(ProviderRequest(intent="make it groovy", current_code='s("bd")'))

    assert result.code == 's("bd*4")'
    assert result.explanation == "Added a steady kick."


@pytest.mark.anyio
async def test_openai_provider_includes_reconciliation_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(json.loads(request.content)["input"])
        assert prompt["current_strudel_code"] == 's("hh")'
        assert prompt["reconciliation"] == {
            "base_strudel_code": 's("bd")',
            "previous_agent_code": 's("bd*4")',
            "user_edit_diff": '+ s("hh")',
            "attempt": 1,
        }
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": '{"code":"s(\\"hh\\")","explanation":"Kept hats.","action":"noop"}'}]}]})

    request = ProviderRequest(
        intent="keep the hats",
        current_code='s("hh")',
        reconciliation=ChangeRequest(
            intent="keep the hats",
            currentCode='s("hh")',
            reconciliation={
                "baseCode": 's("bd")',
                "previousAgentCode": 's("bd*4")',
                "userEditDiff": '+ s("hh")',
                "attempt": 1,
            },
        ).reconciliation,
    )
    result = await OpenAIProvider("test-key", transport=httpx.MockTransport(handler)).create_change(request)

    assert result.action == "noop"


@pytest.mark.anyio
async def test_openai_connection_checks_selected_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models/test-model"
        return httpx.Response(200, json={"id": "test-model"})

    provider = OpenAIProvider("test-key", "test-model", transport=httpx.MockTransport(handler))

    await provider.test_connection()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "message", "retryable"),
    [
        (401, "rejected the API key", False),
        (429, "rate limit", True),
        (500, "unavailable", True),
    ],
)
async def test_openai_maps_http_errors(status: int, message: str, retryable: bool) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"message": "raw"}}))
    provider = OpenAIProvider("test-key", transport=transport)

    with pytest.raises(ProviderError, match=message) as captured:
        await provider.test_connection()

    assert captured.value.retryable is retryable


@pytest.mark.anyio
async def test_openai_maps_timeout_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = OpenAIProvider("super-secret", transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderError, match="timed out") as captured:
        await provider.test_connection()

    assert "super-secret" not in str(captured.value)
