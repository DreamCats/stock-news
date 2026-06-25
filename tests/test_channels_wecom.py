"""企业微信渠道 provider 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stock_news.core.channels import ChannelFile, ChannelMessage, WeComChannelProvider
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


def test_wecom_sends_markdown(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr("stock_news.core.channels.http.urlopen", fake_urlopen)
    provider = _provider()
    target = DeliveryTargetConfig(provider="wecom-main", kind="webhook")

    result = provider.send(
        target_name="wecom-group",
        target=target,
        message=ChannelMessage(markdown="**hello**"),
    )

    assert result.ok is True
    assert captured["url"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
    assert captured["payload"] == {
        "msgtype": "markdown",
        "markdown": {"content": "**hello**"},
    }


def test_wecom_uploads_and_sends_file(monkeypatch: Any, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        body = request.data or b""
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "body": body,
                "timeout": timeout,
            }
        )
        if "upload_media" in request.full_url:
            return FakeResponse({"errcode": 0, "media_id": "media_xxx"})
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr("stock_news.core.channels.http.urlopen", fake_urlopen)
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello", encoding="utf-8")
    provider = _provider()
    target = DeliveryTargetConfig(provider="wecom-main", kind="webhook")

    result = provider.send(
        target_name="wecom-group",
        target=target,
        message=ChannelMessage(file=ChannelFile(path=file_path)),
    )

    assert result.ok is True
    assert calls[0]["url"] == (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key=abc&type=file"
    )
    assert b"report.txt" in calls[0]["body"]
    assert json.loads(calls[1]["body"].decode("utf-8")) == {
        "msgtype": "file",
        "file": {"media_id": "media_xxx"},
    }


def _provider() -> WeComChannelProvider:
    return WeComChannelProvider(
        "wecom-main",
        DeliveryProviderConfig(
            type="wecom_bot",
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
            timeout=12,
        ),
    )
