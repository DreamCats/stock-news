"""微信切片规划测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from stock_news.core.wechat import (
    TimeWindow,
    WechatSQLiteStore,
    build_fetch_slices,
    plan_incremental_slices,
    split_time_window,
)


def test_split_time_window_uses_hour_slices_with_short_tail() -> None:
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 12, 30, tzinfo=timezone.utc),
    )

    slices = split_time_window(window, slice_hours=1)

    got = [
        (item.start.hour, item.start.minute, item.end.hour, item.end.minute)
        for item in slices
    ]
    assert got == [
        (9, 0, 10, 0),
        (10, 0, 11, 0),
        (11, 0, 12, 0),
        (12, 0, 12, 30),
    ]


def test_build_fetch_slices_expands_source_and_window() -> None:
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 11, 0, tzinfo=timezone.utc),
    )

    slices = build_fetch_slices(
        sources=["个人消息", "个人群"],
        windows=[window],
        slice_hours=1,
    )

    got = [
        (item.source, item.window.start.hour, item.window.end.hour) for item in slices
    ]
    assert got == [
        ("个人消息", 9, 10),
        ("个人群", 9, 10),
        ("个人消息", 10, 11),
        ("个人群", 10, 11),
    ]


def test_plan_incremental_slices_skips_safe_successful_window(tmp_path: Path) -> None:
    store = WechatSQLiteStore(tmp_path / "wechat.db")
    first = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )
    full = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 11, 0, tzinfo=timezone.utc),
    )
    store.mark_window_success("个人消息", first, message_count=3)

    slices = plan_incremental_slices(
        sources=["个人消息"],
        windows=[full],
        slice_hours=1,
        store=store,
        now=datetime(2026, 6, 25, 10, 6, tzinfo=timezone.utc),
        safety_margin_minutes=5,
    )

    assert [(item.window.start.hour, item.window.end.hour) for item in slices] == [
        (10, 11)
    ]
