from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import ProviderError, ProviderRequest
from app.providers.deepseek import DeepSeekProvider


@pytest.mark.anyio
async def test_deepseek_provider_uses_json_output_and_parses_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-pro"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert "JSON" in payload["messages"][0]["content"]
        assert json.loads(payload["messages"][1]["content"])["user_intent"] == "add a break"
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps({
                            "code": 's("bd ~ ~ ~")',
                            "explanation": "Opened space for a break.",
                        })
                    },
                }]
            },
        )

    provider = DeepSeekProvider("test-key", transport=httpx.MockTransport(handler))
    result = await provider.create_change(ProviderRequest(intent="add a break", current_code='s("bd*4")'))

    assert result.code == 's("bd ~ ~ ~")'
    assert result.explanation == "Opened space for a break."


@pytest.mark.anyio
async def test_deepseek_connection_checks_model_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models"
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-pro"}]})

    provider = DeepSeekProvider("test-key", transport=httpx.MockTransport(handler))

    await provider.test_connection()


@pytest.mark.anyio
async def test_deepseek_connection_rejects_unavailable_model() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash"}]})
    )
    provider = DeepSeekProvider("test-key", transport=transport)

    with pytest.raises(ProviderError, match="not available"):
        await provider.test_connection()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("choice", "message"),
    [
        ({"finish_reason": "stop", "message": {"content": ""}}, "empty"),
        ({"finish_reason": "length", "message": {"content": "{}"}}, "truncated"),
        ({"finish_reason": "stop", "message": {"content": '{"code":"x"}'}}, "invalid structured"),
    ],
)
async def test_deepseek_rejects_unusable_output(choice: dict, message: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [choice]}))
    provider = DeepSeekProvider("test-key", transport=transport)

    with pytest.raises(ProviderError, match=message):
        await provider.create_change(ProviderRequest(intent="change it", current_code='s("bd")'))
