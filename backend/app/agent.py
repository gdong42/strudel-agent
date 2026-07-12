from __future__ import annotations

from .config import load_config
from .models import ChangeRequest, GeneratedChange
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
                scope=request.scope,
                intensity=request.intensity,
                timing=request.timing,
                avoid=request.avoid,
            )
        )
        if not generated.code.strip():
            raise AgentResponseError("Provider returned empty Strudel code")
        if not generated.explanation.strip():
            raise AgentResponseError("Provider returned an empty explanation")
        return generated


def create_agent_service(provider_name: str | None = None) -> AgentService:
    selected = (provider_name or load_config().agent.provider).strip().lower()
    if selected == "mock":
        return AgentService(MockProvider())
    raise AgentConfigurationError(f'Unknown agent provider: "{selected}"')
