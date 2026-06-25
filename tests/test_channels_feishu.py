"""飞书渠道 provider 测试。"""

from __future__ import annotations

import json
from typing import Any

from stock_news.core.channels import (
    ChannelMessage,
    FeishuChannelProvider,
    RichTextContent,
    RichTextElement,
)
from stock_news.models import DeliveryProviderConfig, DeliveryTargetConfig


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


def test_feishu_sends_rich_text_post(monkeypatch: Any) -> None:
    calls: list[dict[str, object]] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "payload": payload,
                "timeout": timeout,
            }
        )
        if request.full_url.endswith("/auth/v3/app_access_token/internal"):
            return FakeResponse({"code": 0, "tenant_access_token": "tenant-token"})
        return FakeResponse({"code": 0, "data": {"message_id": "om_xxx"}})

    monkeypatch.setattr("stock_news.core.channels.http.urlopen", fake_urlopen)
    provider = FeishuChannelProvider(
        "feishu-main",
        DeliveryProviderConfig(
            type="feishu_bot",
            app_id="cli_xxx",
            app_secret="secret",
            base_url="https://open.feishu.cn",
        ),
    )
    target = DeliveryTargetConfig(
        provider="feishu-main",
        kind="chat",
        id="oc_xxx",
    )
    message = ChannelMessage(
        rich_text=RichTextContent(
            title="标题",
            paragraphs=[
                [
                    RichTextElement(text="正文"),
                    RichTextElement(tag="a", text="链接", href="https://example.com"),
                ]
            ],
        )
    )

    result = provider.send(target_name="dreamboys", target=target, message=message)

    assert result.ok is True
    assert calls[1]["url"].endswith("/im/v1/messages?receive_id_type=chat_id")
    assert calls[1]["payload"]["receive_id"] == "oc_xxx"
    assert calls[1]["payload"]["msg_type"] == "post"
    content = json.loads(str(calls[1]["payload"]["content"]))
    assert content["post"]["zh_cn"]["title"] == "标题"
    assert content["post"]["zh_cn"]["content"][0][1] == {
        "tag": "a",
        "text": "链接",
        "href": "https://example.com",
    }
