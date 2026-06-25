"""LLM provider 选择逻辑测试。"""

from __future__ import annotations

import pytest

from stock_news.core.llm import LLMProviderError, LLMProviderRegistry
from stock_news.models import LLMConfig, LLMProviderConfig


def test_provider_registry_resolves_explicit_provider() -> None:
    cfg = _config()
    registry = LLMProviderRegistry(cfg)

    resolved = registry.resolve(provider="kimi")

    assert resolved.name == "kimi"
    assert resolved.config.model == "kimi-test"


def test_provider_registry_uses_task_pool_before_task_route() -> None:
    cfg = _config()
    cfg.provider_pools["source_extract"] = ["kimi", "glm"]
    cfg.task_routing["source_extract"] = "glm"
    registry = LLMProviderRegistry(cfg)

    assert registry.candidate_names(task="source_extract") == ["kimi", "glm"]


def test_provider_registry_uses_task_route_then_default() -> None:
    cfg = _config()
    cfg.task_routing["classify"] = "glm"
    cfg.default_provider = "kimi"
    registry = LLMProviderRegistry(cfg)

    assert registry.resolve(task="classify").name == "glm"
    assert registry.resolve(task="unknown").name == "kimi"


def test_provider_registry_rejects_missing_provider() -> None:
    cfg = _config()
    registry = LLMProviderRegistry(cfg)

    with pytest.raises(LLMProviderError):
        registry.resolve(provider="missing")


def _config() -> LLMConfig:
    return LLMConfig(
        default_provider="glm",
        providers={
            "glm": LLMProviderConfig(
                base_url="https://glm.example.com/v1",
                api_key="glm-key",
                model="glm-test",
                api="openai",
            ),
            "kimi": LLMProviderConfig(
                base_url="https://kimi.example.com/anthropic",
                api_key="kimi-key",
                model="kimi-test",
                api="anthropic-messages",
            ),
        },
    )
