from app.backend.agent.customer_service_assistance import CustomerServiceAssistanceAgent
from app.backend.agent.openai_compatible_provider import OpenAICompatibleChatProvider
from app.backend.agent.registry import AgentRegistry

ASSISTANCE_AGENT_NAME = "customer_service_assistance"


def create_agent_registry(
    *,
    api_key: str | None = None,
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: str = "qwen3.7-flash",
    timeout_seconds: float = 30.0,
    json_mode: bool = True,
    reasoning_mode: str = "auto",
) -> AgentRegistry:
    registry = AgentRegistry()
    provider = (
        OpenAICompatibleChatProvider(
            api_key, base_url, model, timeout_seconds, json_mode, reasoning_mode
        )
        if api_key
        else None
    )
    registry.register(CustomerServiceAssistanceAgent(provider))
    registry.freeze()
    return registry


__all__ = ["ASSISTANCE_AGENT_NAME", "AgentRegistry", "create_agent_registry"]
