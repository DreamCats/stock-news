"""渠道统一发送入口。

上层只需要传 target 或 route，本层负责选择飞书或企业微信 provider。
"""

from __future__ import annotations

from stock_news.core.channels.feishu import FeishuChannelProvider
from stock_news.core.channels.models import ChannelMessage, ChannelSendResult
from stock_news.core.channels.wecom import WeComChannelProvider
from stock_news.models import (
    ChannelConfig,
    DeliveryProviderConfig,
    DeliveryTargetConfig,
)


class ChannelError(RuntimeError):
    """渠道发送失败。"""


class ChannelSender:
    """按 channel 配置发送消息。"""

    def __init__(self, config: ChannelConfig) -> None:
        self.config = config

    def send_to_target(
        self,
        target_name: str,
        message: ChannelMessage,
    ) -> ChannelSendResult:
        """发送到单个 target。"""

        target = self._target(target_name)
        provider_name, provider = self._provider(target.provider)
        adapter = _provider_adapter(provider_name, provider)
        return adapter.send(
            target_name=target_name,
            target=target,
            message=message,
        )

    def send_to_targets(
        self,
        target_names: list[str],
        message: ChannelMessage,
    ) -> list[ChannelSendResult]:
        """发送到多个 target，单个失败不阻断后续 target。"""

        results: list[ChannelSendResult] = []
        for target_name in target_names:
            try:
                results.append(self.send_to_target(target_name, message))
            except Exception as exc:
                results.append(
                    ChannelSendResult(
                        provider="",
                        target=target_name,
                        ok=False,
                        message=str(exc),
                    )
                )
        return results

    def send_route(
        self,
        route_name: str,
        message: ChannelMessage,
    ) -> list[ChannelSendResult]:
        """发送到 route 下的所有 target。"""

        route = self.config.routes.get(route_name)
        if route is None:
            raise ChannelError(f"渠道 route 未配置: {route_name}")

        results: list[ChannelSendResult] = []
        for target_name in route.targets:
            try:
                results.append(self.send_to_target(target_name, message))
            except Exception as exc:
                result = ChannelSendResult(
                    provider="",
                    target=target_name,
                    ok=False,
                    message=str(exc),
                )
                results.append(result)
                if route.fail_fast:
                    raise ChannelError(str(exc)) from exc
        return results

    def _target(self, name: str) -> DeliveryTargetConfig:
        target = self.config.targets.get(name)
        if target is None:
            raise ChannelError(f"渠道 target 未配置: {name}")
        return target

    def _provider(self, name: str) -> tuple[str, DeliveryProviderConfig]:
        provider = self.config.providers.get(name)
        if provider is None:
            raise ChannelError(f"渠道 provider 未配置: {name}")
        return name, provider


def _provider_adapter(
    name: str,
    config: DeliveryProviderConfig,
) -> FeishuChannelProvider | WeComChannelProvider:
    if config.type == "feishu_bot":
        return FeishuChannelProvider(name, config)
    if config.type == "wecom_bot":
        return WeComChannelProvider(name, config)
    raise ChannelError(f"不支持的渠道 provider 类型: {config.type}")
