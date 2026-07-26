from __future__ import annotations

import pytest

from app.agent import AgentConfigurationError, AgentResponseError, AgentService, create_agent_service
from app.config import AgentConfig, ProjectConfig
from app.models import ChangeRequest, GeneratedChange
from app.providers.base import ProviderRequest
from app.providers.mock import MockProvider


class StubProvider:
    def __init__(self, response: GeneratedChange) -> None:
        self.response = response
        self.request: ProviderRequest | None = None

    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        self.request = request
        return self.response


@pytest.mark.anyio
async def test_agent_maps_change_request_to_provider_contract() -> None:
    provider = StubProvider(GeneratedChange(code='s("bd*4")', explanation="More energy."))
    service = AgentService(provider)

    result = await service.create_change(
        ChangeRequest(
            intent="  add energy  ",
            currentCode='s("bd")',
            applyMode="auto",
        )
    )

    assert result.code == 's("bd*4")'
    assert result.provider == "unknown"
    assert result.latency_ms >= 0
    assert provider.request == ProviderRequest(
        intent="add energy",
        current_code='s("bd")',
    )


@pytest.mark.anyio
async def test_agent_maps_reconciliation_context_to_provider_contract() -> None:
    provider = StubProvider(GeneratedChange(code='s("hh")', explanation="Kept the hats."))
    service = AgentService(provider)

    await service.create_change(
        ChangeRequest(
            intent="keep the hats",
            currentCode='s("hh")',
            reconciliation={
                "baseCode": 's("bd")',
                "previousAgentCode": 's("bd*4")',
                "userEditDiff": '+ s("hh")',
                "attempt": 1,
            },
        )
    )

    assert provider.request is not None
    assert provider.request.reconciliation is not None
    assert provider.request.reconciliation.previous_agent_code == 's("bd*4")'


@pytest.mark.anyio
async def test_agent_rejects_empty_provider_code() -> None:
    service = AgentService(StubProvider(GeneratedChange(code=" ", explanation="Nothing.")))

    with pytest.raises(AgentResponseError, match="empty Strudel code"):
        await service.create_change(ChangeRequest(intent="change it", currentCode='s("bd")'))


@pytest.mark.anyio
async def test_agent_rejects_noop_that_changes_code() -> None:
    service = AgentService(StubProvider(GeneratedChange(code='s("hh")', explanation="No change.", action="noop")))

    with pytest.raises(AgentResponseError, match="no-op"):
        await service.create_change(ChangeRequest(intent="change it", currentCode='s("bd")'))


@pytest.mark.anyio
async def test_mock_provider_is_deterministic() -> None:
    request = ProviderRequest(intent="add energy", current_code='s("bd")')

    first = await MockProvider().create_change(request)
    second = await MockProvider().create_change(request)

    assert first == second
    assert "Agent draft: add energy" in first.code


@pytest.mark.anyio
async def test_mock_provider_can_return_a_reconciliation_noop() -> None:
    marker = "// Agent draft: add energy"
    result = await MockProvider().create_change(
        ProviderRequest(
            intent="add energy",
            current_code=f's("bd")\n{marker}\n',
            reconciliation=ChangeRequest(
                intent="add energy",
                currentCode=f's("bd")\n{marker}\n',
                reconciliation={
                    "baseCode": 's("bd")',
                    "previousAgentCode": f's("bd")\n{marker}\n',
                    "userEditDiff": f'+ {marker}',
                    "attempt": 1,
                },
            ).reconciliation,
        )
    )

    assert result.action == "noop"


def test_unknown_provider_is_a_configuration_error() -> None:
    with pytest.raises(AgentConfigurationError, match="unknown-provider"):
        create_agent_service("unknown-provider")


def test_openai_requires_an_api_key() -> None:
    with pytest.raises(AgentConfigurationError, match="API key"):
        create_agent_service("openai")


def test_deepseek_requires_an_api_key() -> None:
    with pytest.raises(AgentConfigurationError, match="DeepSeek API key"):
        create_agent_service("deepseek")


def test_openai_uses_configured_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agent.load_config",
        lambda: ProjectConfig(agent=AgentConfig(provider="openai", model="configured-model")),
    )

    service = create_agent_service(api_key="test-key")

    assert service.provider_name == "openai"
    assert service.model == "configured-model"
