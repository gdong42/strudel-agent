from __future__ import annotations

import json

import pytest

from app.agent import AgentConfigurationError, create_agent_service
from app.config import AgentConfig, ProjectConfig
from app.models import AgentMessage, ModelTurnRequest
from app.providers.mock import MockProvider


@pytest.mark.anyio
async def test_mock_provider_implements_model_turn_contract() -> None:
    result = await MockProvider().next_turn(
        ModelTurnRequest(
            messages=[
                AgentMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "intent": "Make it more energetic.",
                            "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
                        }
                    ),
                )
            ],
            tools=[],
            model="mock",
            maxOutputTokens=100,
        )
    )

    assert result.assistant_message.role == "assistant"
    assert result.assistant_message.tool_calls[0].name == "finalize_change"
    assert result.assistant_message.tool_calls[0].arguments["code"] == 's("bd")\n\n// Agent draft: Make it more energetic.\n'
    assert result.usage.total_tokens == 0


@pytest.mark.anyio
async def test_mock_provider_creates_starter_code_for_an_empty_project() -> None:
    result = await MockProvider().next_turn(
        ModelTurnRequest(
            messages=[
                AgentMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "intent": "Start a minimal house beat.",
                            "editorVersion": {"code": "", "hash": "empty-hash"},
                        }
                    ),
                )
            ],
            tools=[],
            model="mock",
            maxOutputTokens=100,
        )
    )

    assert result.assistant_message.tool_calls[0].arguments["code"] == (
        's("bd*4")\n\n// Agent draft: Start a minimal house beat.\n'
    )


@pytest.mark.anyio
async def test_mock_provider_uses_the_latest_runtime_editor_version() -> None:
    result = await MockProvider().next_turn(
        ModelTurnRequest(
            messages=[
                AgentMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "intent": "Make it more energetic.",
                            "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
                        }
                    ),
                ),
                AgentMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "editorUpdate": {
                                "baseHash": "editor-hash",
                                "editorVersion": {"code": 's("hh")', "hash": "latest-hash"},
                            }
                        }
                    ),
                ),
            ],
            tools=[],
            model="mock",
            maxOutputTokens=100,
        )
    )

    assert result.assistant_message.tool_calls[0].arguments["code"] == (
        's("hh")\n\n// Agent draft: Make it more energetic.\n'
    )


def test_unknown_provider_is_a_configuration_error() -> None:
    with pytest.raises(AgentConfigurationError, match="unknown-provider"):
        create_agent_service("unknown-provider")


def test_openai_requires_an_api_key() -> None:
    with pytest.raises(AgentConfigurationError, match="API key"):
        create_agent_service("openai")


def test_deepseek_requires_an_api_key() -> None:
    with pytest.raises(AgentConfigurationError, match="DeepSeek API key"):
        create_agent_service("deepseek")


def test_kimi_requires_an_api_key() -> None:
    with pytest.raises(AgentConfigurationError, match="Kimi API key"):
        create_agent_service("kimi")


def test_kimi_uses_its_default_model() -> None:
    service = create_agent_service("kimi", api_key="test-key")

    assert service.provider_name == "kimi"
    assert service.model == "kimi-k3"


def test_openai_uses_configured_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agent.load_config",
        lambda: ProjectConfig(agent=AgentConfig(provider="openai", model="configured-model")),
    )

    service = create_agent_service(api_key="test-key")

    assert service.provider_name == "openai"
    assert service.model == "configured-model"
