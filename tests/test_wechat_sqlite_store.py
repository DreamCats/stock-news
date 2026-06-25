"""微信 SQLite 增量存储测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from stock_news.core.wechat import TimeWindow, WechatMessage, WechatSQLiteStore


def test_save_messages_is_incremental(tmp_path: Path) -> None:
    store = WechatSQLiteStore(tmp_path / "wechat.db")
    first = _message("继续关注国产算力", minute=1)
    second = _message("液冷方向有新催化", minute=2)

    first_summary = store.save_messages([first, first])
    second_summary = store.save_messages([first, second])

    assert first_summary.total == 2
    assert first_summary.inserted == 1
    assert first_summary.duplicated == 1
    assert second_summary.inserted == 1
    assert second_summary.duplicated == 1
    assert [item.content for item in store.list_messages()] == [
        "继续关注国产算力",
        "液冷方向有新催化",
    ]


def test_successful_safe_window_is_skipped(tmp_path: Path) -> None:
    store = WechatSQLiteStore(tmp_path / "wechat.db")
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )

    store.mark_window_success("个人消息", window, message_count=3)

    assert not store.should_fetch_window(
        "个人消息",
        window,
        now=datetime(2026, 6, 25, 10, 6, tzinfo=timezone.utc),
        safety_margin_minutes=5,
    )


def test_recent_successful_window_is_fetched_again(tmp_path: Path) -> None:
    store = WechatSQLiteStore(tmp_path / "wechat.db")
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )

    store.mark_window_success("个人消息", window, message_count=3)

    assert store.should_fetch_window(
        "个人消息",
        window,
        now=datetime(2026, 6, 25, 10, 4, tzinfo=timezone.utc),
        safety_margin_minutes=5,
    )


def test_failed_window_is_fetched_again(tmp_path: Path) -> None:
    store = WechatSQLiteStore(tmp_path / "wechat.db")
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )

    store.mark_window_failure("个人消息", window, error="timeout")

    assert store.should_fetch_window(
        "个人消息",
        window,
        now=datetime(2026, 6, 25, 10, 6, tzinfo=timezone.utc),
        safety_margin_minutes=5,
    )


def _message(content: str, *, minute: int) -> WechatMessage:
    return WechatMessage(
        source="个人消息",
        sender="测试发送人",
        message_time=datetime(2026, 6, 25, 9, minute, tzinfo=timezone.utc),
        content=content,
        raw={"content": content},
    )
