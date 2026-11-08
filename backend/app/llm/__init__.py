from ..config import Settings
from ..config import settings as default_settings
from .base import LLMError, LLMResponse, Message, Provider, ToolCall, ToolSpec


def get_provider(cfg: Settings = default_settings, name: str | None = None) -> Provider:
    name = (name or cfg.llm_provider).lower()
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg.openai_api_key, cfg.openai_model, cfg.openai_base_url, cfg.llm_timeout)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg.anthropic_api_key, cfg.anthropic_model, cfg.llm_timeout)
    if name == "offline":
        from .offline import OfflineProvider

        return OfflineProvider()
    raise LLMError(f"unknown LLM provider {name!r}")


__all__ = ["LLMError", "LLMResponse", "Message", "Provider", "ToolCall", "ToolSpec", "get_provider"]
