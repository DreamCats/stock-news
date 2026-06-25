"""渠道统一发送入口测试。"""

from __future__ import annotations

import json
from typing import Any

from stock_news.core.channels import ChannelMessage, ChannelSender
from stock_news.models import (
    ChannelConfig,
    DeliveryProviderConfig,
    DeliveryRouteConfig,
    DeliveryTargetConfig,
)


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


def test_channel_sender_sends_route_targets(monkeypatch: Any) -> None:
    payloads: list[dict[str, object]] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr("stock_news.core.channels.http.urlopen", fake_urlopen)
    sender = ChannelSender(
        ChannelConfig(
            providers={
                "wecom-main": DeliveryProviderConfig(
                    type="wecom_bot",
                    webhook_url=(
                        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
                    ),
                )
            },
            targets={
                "group-a": DeliveryTargetConfig(
                    provider="wecom-main",
                    kind="webhook",
                ),
                "group-b": DeliveryTargetConfig(
                    provider="wecom-main",
                    kind="webhook",
                ),
            },
            routes={
                "default": DeliveryRouteConfig(
                    targets=["group-a", "group-b"],
                    format="markdown",
                )
            },
        )
    )

    results = sender.send_route("default", ChannelMessage(text="hello"))

    assert [item.ok for item in results] == [True, True]
    assert payloads == [
        {"msgtype": "text", "text": {"content": "hello"}},
        {"msgtype": "text", "text": {"content": "hello"}},
    ]
