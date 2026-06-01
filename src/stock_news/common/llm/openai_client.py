"""OpenAI Chat Completions 协议适配."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from stock_news.models import LLMProviderConfig


def chat_openai(
    provider: LLMProviderConfig,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    disable_thinking: bool = False,
) -> str:
    client = OpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key or "no-key",
        timeout=provider.timeout,
        default_headers=provider.headers or None,
    )
    kwargs: dict[str, Any] = {
        "model": model or provider.model,
        "messages": messages,
        "temperature": temperature if temperature is not None else provider.temperature,
    }
    effective_max = max_tokens or provider.max_tokens
    if effective_max:
        kwargs["max_tokens"] = effective_max
    if disable_thinking:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content
    return content or ""
