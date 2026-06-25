"""微信 CLI 参数解析测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_news.commands.wechat_cli import _resolve_window


def test_resolve_last_keeps_second_precision() -> None:
    now = datetime(2026, 6, 25, 15, 30, 34, tzinfo=timezone.utc)

    window = _resolve_window(last="30m", start=None, end=None, now=now)

    assert window.start == datetime(2026, 6, 25, 15, 0, 34, tzinfo=timezone.utc)
    assert window.end == now
    assert window.start.microsecond == 0
    assert window.end.microsecond == 0
