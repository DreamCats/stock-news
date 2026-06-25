"""LLM core 能力。

这里提供 provider 选择、OpenAI 协议和 Anthropic 协议的统一聊天入口。
"""

from stock_news.core.llm.client import LLMClient, LLMClientError
from stock_news.core.llm.models import ChatMessage, ChatResult, ChatRole
from stock_news.core.llm.provider import (
    LLMProviderError,
    LLMProviderRegistry,
    ResolvedProvider,
)

__all__ = [
    "ChatMessage",
    "ChatResult",
    "ChatRole",
    "LLMClient",
    "LLMClientError",
    "LLMProviderError",
    "LLMProviderRegistry",
    "ResolvedProvider",
]
