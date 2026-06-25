"""LLM provider 选择逻辑。

这里只负责从配置里挑 provider，不负责发起 HTTP 请求。
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_news.models import LLMConfig, LLMProviderConfig


class LLMProviderError(ValueError):
    """LLM provider 配置错误。"""


@dataclass(frozen=True)
class ResolvedProvider:
    """已解析的 provider 配置。"""

    name: str
    config: LLMProviderConfig


class LLMProviderRegistry:
    """从 LLMConfig 里解析 provider。"""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def resolve(
        self,
        *,
        provider: str | None = None,
        task: str | None = None,
    ) -> ResolvedProvider:
        """解析单个 provider。"""

        names = self.candidate_names(provider=provider, task=task)
        if not names:
            raise LLMProviderError("未配置可用的模型 provider")
        return self._resolve_name(names[0])

    def candidate_names(
        self,
        *,
        provider: str | None = None,
        task: str | None = None,
    ) -> list[str]:
        """返回候选 provider 名称，顺序即 fallback 顺序。"""

        if provider:
            self._resolve_name(provider)
            return [provider]
        if task and task in self.config.provider_pools:
            names = self.config.provider_pools[task]
            return [self._resolve_name(name).name for name in names]
        if task and task in self.config.task_routing:
            name = self.config.task_routing[task]
            self._resolve_name(name)
            return [name]
        if self.config.default_provider:
            self._resolve_name(self.config.default_provider)
            return [self.config.default_provider]
        if len(self.config.providers) == 1:
            return [next(iter(self.config.providers))]
        return []

    def _resolve_name(self, name: str) -> ResolvedProvider:
        provider = self.config.providers.get(name)
        if provider is None:
            raise LLMProviderError(f"模型 provider 未配置: {name}")
        return ResolvedProvider(name=name, config=provider)
