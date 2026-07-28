from __future__ import annotations

from .config import load_config
from .models import ProviderInfo
from .providers.base import AgentProvider
from .providers.deepseek import DEFAULT_DEEPSEEK_MODEL, DeepSeekProvider
from .providers.mock import MockProvider
from .providers.openai import DEFAULT_OPENAI_MODEL, OpenAIProvider


class AgentConfigurationError(RuntimeError):
    pass


class AgentService:
    def __init__(self, provider: AgentProvider, provider_name: str = "unknown", model: str | None = None) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model

    async def test_connection(self) -> None:
        await self.provider.test_connection()


def create_agent_service(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> AgentService:
    config = load_config().agent
    selected = (provider_name or config.provider).strip().lower()
    if selected == "mock":
        return AgentService(MockProvider(), "mock")
    if selected == "openai":
        if not api_key:
            raise AgentConfigurationError("OpenAI API key is not configured")
        configured_model = config.model if selected == config.provider.lower() else None
        selected_model = model or configured_model or DEFAULT_OPENAI_MODEL
        return AgentService(OpenAIProvider(api_key, selected_model), "openai", selected_model)
    if selected == "deepseek":
        if not api_key:
            raise AgentConfigurationError("DeepSeek API key is not configured")
        configured_model = config.model if selected == config.provider.lower() else None
        selected_model = model or configured_model or DEFAULT_DEEPSEEK_MODEL
        return AgentService(DeepSeekProvider(api_key, selected_model), "deepseek", selected_model)
    raise AgentConfigurationError(f'Unknown agent provider: "{selected}"')


def list_provider_info() -> list[ProviderInfo]:
    return [
        ProviderInfo(id="mock", label="Mock", requiresApiKey=False),
        ProviderInfo(
            id="deepseek",
            label="DeepSeek",
            requiresApiKey=True,
            defaultModel=DEFAULT_DEEPSEEK_MODEL,
        ),
        ProviderInfo(
            id="openai",
            label="OpenAI",
            requiresApiKey=True,
            defaultModel=DEFAULT_OPENAI_MODEL,
        ),
    ]
