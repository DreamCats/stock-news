"""Anthropic Messages 协议适配."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from stock_news.models import LLMProviderConfig


def _normalize_base_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    return trimmed[:-3] if trimmed.endswith("/v1") else trimmed


def _headers(provider: LLMProviderConfig) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Anthropic-Version": "2023-06-01",
        **provider.headers,
    }
    hostname = urlparse(provider.base_url).hostname or ""
    if hostname.lower() == "api.anthropic.com":
        headers["X-Api-Key"] = provider.api_key
    else:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    return headers


def _payload(
    provider: LLMProviderConfig,
    messages: list[dict[str, str]],
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    disable_thinking: bool,
) -> dict[str, object]:
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role in {"user", "assistant"}:
            anthropic_messages.append({"role": role, "content": content})
        else:
            anthropic_messages.append({"role": "user", "content": content})

    payload: dict[str, object] = {
        "model": model or provider.model,
        "messages": anthropic_messages,
        "temperature": temperature if temperature is not None else provider.temperature,
        "max_tokens": max_tokens or provider.max_tokens or 8192,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if disable_thinking:
        payload["thinking"] = {"type": "disabled"}
    return payload


def chat_anthropic(
    provider: LLMProviderConfig,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    disable_thinking: bool = False,
) -> str:
    url = f"{_normalize_base_url(provider.base_url)}/v1/messages"
    with httpx.Client(timeout=provider.timeout) as client:
        resp = client.post(
            url,
            headers=_headers(provider),
            json=_payload(
                provider,
                messages,
                model,
                temperature,
                max_tokens,
                disable_thinking,
            ),
        )
        resp.raise_for_status()
        data = resp.json()

    blocks = data.get("content") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)
