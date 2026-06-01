"""LLM 客户端入口：provider 解析、限速、重试和 JSON 包装."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from typing import cast

import httpx
from openai import RateLimitError

from stock_news.common.config import load
from stock_news.common.exceptions import ConfigError
from stock_news.common.llm.anthropic_client import chat_anthropic
from stock_news.common.llm.openai_client import chat_openai
from stock_news.models import LLMProviderConfig

_MAX_RETRIES = 5
_BASE_DELAY = 2.0  # 首次重试等 2s，之后 4s, 8s, 16s, 32s

# -- 全局 RPM 限速器 --
_RPM_LIMIT = 90  # 留 10% 余量 (实际 RPM:100)
_rpm_lock = threading.Lock()
_rpm_timestamps: list[float] = []


def _rpm_wait() -> None:
    """在发请求前调用，确保不超过 RPM 限制。多线程安全。"""
    while True:
        with _rpm_lock:
            now = time.monotonic()
            # 清理 60s 之前的记录
            while _rpm_timestamps and _rpm_timestamps[0] < now - 60:
                _rpm_timestamps.pop(0)
            if len(_rpm_timestamps) < _RPM_LIMIT:
                _rpm_timestamps.append(now)
                return
            # 算出最早记录过期的时间
            wait = _rpm_timestamps[0] - (now - 60) + 0.1
        time.sleep(wait)


def _resolve_provider(
    provider_name: str | None = None,
) -> tuple[str, LLMProviderConfig]:
    """解析 provider 名称和配置."""
    cfg = load()
    if not cfg.llm.providers:
        raise ConfigError(
            "未配置 LLM provider，请先运行: "
            "sn llm add <name> --base-url ... --model ... --api-key ..."
        )

    name = provider_name or cfg.llm.default_provider
    if not name:
        name = next(iter(cfg.llm.providers))

    if name not in cfg.llm.providers:
        available = ", ".join(cfg.llm.providers)
        raise ConfigError(f"LLM provider '{name}' 不存在，可用: {available}")

    return name, cfg.llm.providers[name]


ChatFn = Callable[
    [
        LLMProviderConfig,
        list[dict[str, str]],
        str | None,
        float | None,
        int | None,
        bool,
    ],
    str,
]


def _chat_impl(provider: LLMProviderConfig) -> ChatFn:
    if provider.api == "anthropic-messages":
        return chat_anthropic
    return chat_openai


def get_provider_for_task(task: str) -> tuple[str, LLMProviderConfig]:
    """根据 task_routing 获取指定任务的 provider."""
    cfg = load()
    provider_name = cfg.llm.task_routing.get(task)
    return _resolve_provider(provider_name)


def chat(
    messages: list[dict[str, str]],
    provider_name: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    disable_thinking: bool = False,
) -> str:
    """发送聊天请求，返回文本."""
    name, provider = _resolve_provider(provider_name)
    impl = _chat_impl(provider)

    for attempt in range(_MAX_RETRIES + 1):
        _rpm_wait()
        try:
            return impl(
                provider,
                messages,
                model,
                temperature,
                max_tokens,
                disable_thinking,
            )
        except (RateLimitError, httpx.HTTPStatusError) as exc:
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code != 429
            ):
                raise
            if attempt == _MAX_RETRIES:
                raise
            delay = _BASE_DELAY * (2**attempt)
            sys.stderr.write(
                "  ⏳ 429 限频，"
                f"{delay:.0f}s 后重试 ({attempt + 1}/{_MAX_RETRIES})...\n"
            )
            sys.stderr.flush()
            time.sleep(delay)
    return ""


def chat_json(
    messages: list[dict[str, str]],
    provider_name: str | None = None,
    model: str | None = None,
    disable_thinking: bool = False,
) -> dict[str, object]:
    """发送请求并解析 JSON 返回，解析失败重试一次."""
    for attempt in range(2):
        raw = chat(messages, provider_name, model, disable_thinking=disable_thinking)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "返回格式不是合法 JSON，请重新输出纯 JSON，"
                            "不要包含 markdown 代码块。"
                        ),
                    },
                ]
                continue
            raise
    return {}


def chat_json_list(
    messages: list[dict[str, str]],
    provider_name: str | None = None,
    model: str | None = None,
    disable_thinking: bool = False,
) -> list[dict[str, object]]:
    """发送请求并解析 JSON 数组返回."""
    for attempt in range(2):
        raw = chat(messages, provider_name, model, disable_thinking=disable_thinking)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return cast(list[dict[str, object]], parsed)
            if isinstance(parsed, dict):
                return [parsed]
            return []
        except json.JSONDecodeError:
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "返回格式不是合法 JSON 数组，请重新输出纯 JSON 数组，"
                            "不要包含 markdown 代码块。"
                        ),
                    },
                ]
                continue
            raise
    return []


def test_connection(provider_name: str | None = None) -> dict[str, str]:
    """测试 LLM 连通性."""
    name, provider = _resolve_provider(provider_name)
    try:
        reply = chat(
            [{"role": "user", "content": "回复 ok"}],
            provider_name=name,
        )
        return {
            "provider": name,
            "model": provider.model,
            "status": "ok",
            "reply": reply.strip(),
        }
    except Exception as e:
        return {
            "provider": name,
            "model": provider.model,
            "status": "error",
            "error": str(e),
        }
