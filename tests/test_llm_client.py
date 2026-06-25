"""LLM 协议客户端测试。"""

from __future__ import annotations

import json
from typing import Any

from stock_news.core.llm import ChatMessage, LLMClient
from stock_news.models import LLMConfig, LLMProviderConfig


class FakeResponse:
    """假的 HTTP 响应。"""

    def __init__(self, body: dict[str, object]) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


def test_openai_chat_completions_request(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"choices": [{"message": {"content": "openai response"}}]})

    monkeypatch.setattr("stock_news.core.llm.client.urlopen", fake_urlopen)
    client = LLMClient(
        LLMConfig(
            default_provider="openai-main",
            providers={
                "openai-main": LLMProviderConfig(
                    base_url="https://api.example.com/v1",
                    api_key="openai-key",
                    model="openai-test",
                    api="openai",
                    temperature=0.2,
                    timeout=12.0,
                )
            },
        )
    )

    result = client.chat_text("hello")

    headers = _lower_headers(captured["headers"])
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["timeout"] == 12.0
    assert headers["authorization"] == "Bearer openai-key"
    assert captured["payload"] == {
        "model": "openai-test",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.2,
    }
    assert result.provider == "openai-main"
    assert result.content == "openai response"


def test_anthropic_messages_request_splits_system(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {"content": [{"type": "text", "text": "anthropic response"}]}
        )

    monkeypatch.setattr("stock_news.core.llm.client.urlopen", fake_urlopen)
    client = LLMClient(
        LLMConfig(
            default_provider="kimi",
            providers={
                "kimi": LLMProviderConfig(
                    base_url="https://kimi.example.com/anthropic",
                    api_key="kimi-key",
                    model="kimi-test",
                    api="anthropic-messages",
                    headers={"User-Agent": "stock-news-test"},
                    max_tokens=1024,
                    temperature=0.3,
                    timeout=15.0,
                )
            },
        )
    )

    result = client.chat(
        [
            ChatMessage(role="system", content="你是投研助手"),
            ChatMessage(role="user", content="总结消息"),
        ]
    )

    headers = _lower_headers(captured["headers"])
    assert captured["url"] == "https://kimi.example.com/anthropic/v1/messages"
    assert captured["timeout"] == 15.0
    assert headers["x-api-key"] == "kimi-key"
    assert headers["authorization"] == "Bearer kimi-key"
    assert headers["user-agent"] == "stock-news-test"
    assert captured["payload"] == {
        "model": "kimi-test",
        "messages": [{"role": "user", "content": "总结消息"}],
        "temperature": 0.3,
        "system": "你是投研助手",
        "max_tokens": 1024,
    }
    assert "thinking" not in captured["payload"]
    assert result.provider == "kimi"
    assert result.content == "anthropic response"


def test_anthropic_messages_can_enable_thinking(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"content": [{"type": "text", "text": "with thinking"}]})

    monkeypatch.setattr("stock_news.core.llm.client.urlopen", fake_urlopen)
    client = LLMClient(
        LLMConfig(
            default_provider="claude",
            providers={
                "claude": LLMProviderConfig(
                    base_url="https://claude.example.com/v1",
                    api_key="claude-key",
                    model="claude-test",
                    api="anthropic-messages",
                    thinking_enabled=True,
                    thinking_budget_tokens=2048,
                )
            },
        )
    )

    result = client.chat_text("hello")

    assert captured["payload"]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
    }
    assert result.content == "with thinking"


def test_llm_client_falls_back_provider_pool(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        calls.append(request.full_url)
        if len(calls) == 1:
            raise TimeoutError("timeout")
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("stock_news.core.llm.client.urlopen", fake_urlopen)
    client = LLMClient(
        LLMConfig(
            provider_pools={"classify": ["bad", "good"]},
            providers={
                "bad": LLMProviderConfig(
                    base_url="https://bad.example.com/v1",
                    api_key="bad-key",
                    model="bad-test",
                    api="openai",
                ),
                "good": LLMProviderConfig(
                    base_url="https://good.example.com/v1",
                    api_key="good-key",
                    model="good-test",
                    api="openai",
                ),
            },
        )
    )

    result = client.chat_text("hello", task="classify")

    assert calls == [
        "https://bad.example.com/v1/chat/completions",
        "https://good.example.com/v1/chat/completions",
    ]
    assert result.provider == "good"
    assert result.content == "ok"


def _lower_headers(headers: object) -> dict[str, str]:
    assert isinstance(headers, dict)
    return {str(key).lower(): str(value) for key, value in headers.items()}
