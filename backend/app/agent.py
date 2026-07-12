from __future__ import annotations

from .config import load_config
from .models import ChangeRequest, GeneratedChange, ProviderInfo
from .providers.base import AgentProvider, ProviderRequest
from .providers.mock import MockProvider


class AgentConfigurationError(RuntimeError):
    pass


class AgentResponseError(RuntimeError):
    pass


class AgentService:
    def __init__(self, provider: AgentProvider) -> None:
        self.provider = provider

    async def create_change(self, request: ChangeRequest) -> GeneratedChange:
        generated = await self.provider.create_change(
            ProviderRequest(
                intent=request.intent.strip(),
                current_code=request.current_code,
            )
        )
        if not generated.code.strip():
            raise AgentResponseError("Provider returned empty Strudel code")
        if not generated.explanation.strip():
            raise AgentResponseError("Provider returned an empty explanation")
        return generated

    async def test_connection(self) -> None:
        await self.provider.test_connection()


def create_agent_service(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> AgentService:
    selected = (provider_name or load_config().agent.provider).strip().lower()
    if selected == "mock":
        return AgentService(MockProvider())
    raise AgentConfigurationError(f'Unknown agent provider: "{selected}"')


def list_provider_info() -> list[ProviderInfo]:
    return [ProviderInfo(id="mock", label="Mock", requiresApiKey=False)]
