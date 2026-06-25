"""LLM HTTP 客户端。

当前支持 OpenAI chat completions 协议和 Anthropic messages 协议。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from stock_news.core.llm.models import ChatMessage, ChatResult
from stock_news.core.llm.provider import LLMProviderRegistry
from stock_news.models import LLMConfig, LLMProviderConfig


class LLMClientError(RuntimeError):
    """LLM 调用失败。"""


class LLMClient:
    """根据配置调用模型 provider。"""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.registry = LLMProviderRegistry(config)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        provider: str | None = None,
        task: str | None = None,
    ) -> ChatResult:
        """调用模型并返回文本结果。"""

        names = self.registry.candidate_names(provider=provider, task=task)
        errors: list[str] = []
        for name in names:
            resolved = self.registry.resolve(provider=name)
            try:
                return _chat_once(name, resolved.config, messages)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            raise LLMClientError("所有模型 provider 调用失败: " + "; ".join(errors))
        raise LLMClientError("未配置可用的模型 provider")

    def chat_text(
        self,
        prompt: str,
        *,
        system: str = "",
        provider: str | None = None,
        task: str | None = None,
    ) -> ChatResult:
        """用普通 prompt 调用模型。"""

        messages: list[ChatMessage] = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=prompt))
        return self.chat(messages, provider=provider, task=task)


def _chat_once(
    provider_name: str,
    provider: LLMProviderConfig,
    messages: list[ChatMessage],
) -> ChatResult:
    if provider.api in ("openai", "openai-completions"):
        return _chat_openai(provider_name, provider, messages)
    if provider.api == "anthropic-messages":
        return _chat_anthropic(provider_name, provider, messages)
    raise LLMClientError(f"不支持的模型协议: {provider.api}")


def _chat_openai(
    provider_name: str,
    provider: LLMProviderConfig,
    messages: list[ChatMessage],
) -> ChatResult:
    payload: dict[str, object] = {
        "model": provider.model,
        "messages": [
            {"role": message.role, "content": message.content} for message in messages
        ],
        "temperature": provider.temperature,
    }
    if provider.max_tokens is not None:
        payload["max_tokens"] = provider.max_tokens
    data = _post_json(
        url=_openai_chat_url(provider.base_url),
        payload=payload,
        headers=_openai_headers(provider),
        timeout=provider.timeout,
    )
    content = _openai_content(data)
    return ChatResult(
        provider=provider_name,
        model=provider.model,
        content=content,
        raw=data,
    )


def _chat_anthropic(
    provider_name: str,
    provider: LLMProviderConfig,
    messages: list[ChatMessage],
) -> ChatResult:
    system_messages = [item.content for item in messages if item.role == "system"]
    chat_messages = [item for item in messages if item.role != "system"]
    if not chat_messages:
        raise LLMClientError("Anthropic messages 至少需要一条 user/assistant 消息")

    payload: dict[str, object] = {
        "model": provider.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in chat_messages
        ],
        "temperature": provider.temperature,
    }
    if system_messages:
        payload["system"] = "\n\n".join(system_messages)
    if provider.max_tokens is not None:
        payload["max_tokens"] = provider.max_tokens
    if provider.thinking_enabled:
        payload["thinking"] = _anthropic_thinking(provider)
    data = _post_json(
        url=_anthropic_messages_url(provider.base_url),
        payload=payload,
        headers=_anthropic_headers(provider),
        timeout=provider.timeout,
    )
    content = _anthropic_content(data)
    return ChatResult(
        provider=provider_name,
        model=provider.model,
        content=content,
        raw=data,
    )


def _post_json(
    *,
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMClientError(f"LLM HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise LLMClientError(f"LLM 请求失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMClientError("LLM 请求超时") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMClientError("LLM 响应不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise LLMClientError("LLM 响应必须是 JSON object")
    return data


def _openai_headers(provider: LLMProviderConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    headers.update(provider.headers)
    return headers


def _anthropic_headers(provider: LLMProviderConfig) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if provider.api_key:
        headers["x-api-key"] = provider.api_key
        headers["Authorization"] = f"Bearer {provider.api_key}"
    headers.update(provider.headers)
    return headers


def _anthropic_thinking(provider: LLMProviderConfig) -> dict[str, object]:
    thinking: dict[str, object] = {"type": "enabled"}
    if provider.thinking_budget_tokens is not None:
        thinking["budget_tokens"] = provider.thinking_budget_tokens
    return thinking


def _openai_chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _anthropic_messages_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _openai_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMClientError("OpenAI 响应缺少 choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMClientError("OpenAI choices[0] 必须是 object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMClientError("OpenAI choices[0].message 必须是 object")
    return _content_to_text(message.get("content"))


def _anthropic_content(data: dict[str, Any]) -> str:
    return _content_to_text(data.get("content"))


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(str(item["text"]))
        if texts:
            return "".join(texts)
    raise LLMClientError("LLM 响应缺少文本内容")
