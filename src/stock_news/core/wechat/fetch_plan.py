"""微信拉取切片规划。

这里把用户给定的大时间窗口拆成固定小时切片，并结合 SQLite 状态过滤已完成窗口。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from stock_news.core.wechat.models import TimeWindow
from stock_news.core.wechat.sqlite_store import WechatSQLiteStore


@dataclass(frozen=True)
class FetchSlice:
    """一个待拉取的微信切片任务。"""

    source: str
    window: TimeWindow


def split_time_window(window: TimeWindow, *, slice_hours: int) -> list[TimeWindow]:
    """把大窗口拆成左闭右开的小时切片。"""

    if slice_hours < 1:
        raise ValueError("slice_hours 必须大于等于 1")

    step = timedelta(hours=slice_hours)
    out: list[TimeWindow] = []
    current = window.start
    while current < window.end:
        next_end = min(current + step, window.end)
        out.append(TimeWindow(start=current, end=next_end))
        current = next_end
    return out


def build_fetch_slices(
    *,
    sources: Sequence[str],
    windows: Sequence[TimeWindow],
    slice_hours: int,
) -> list[FetchSlice]:
    """按 source 和时间切片展开完整拉取计划。"""

    slices: list[FetchSlice] = []
    for window in windows:
        for sliced in split_time_window(window, slice_hours=slice_hours):
            for source in sources:
                slices.append(FetchSlice(source=source, window=sliced))
    return slices


def plan_incremental_slices(
    *,
    sources: Sequence[str],
    windows: Sequence[TimeWindow],
    slice_hours: int,
    store: WechatSQLiteStore,
    now: datetime,
    safety_margin_minutes: int,
) -> list[FetchSlice]:
    """生成增量拉取计划，跳过已成功且安全结束的切片。"""

    return [
        fetch_slice
        for fetch_slice in build_fetch_slices(
            sources=sources,
            windows=windows,
            slice_hours=slice_hours,
        )
        if store.should_fetch_window(
            fetch_slice.source,
            fetch_slice.window,
            now=now,
            safety_margin_minutes=safety_margin_minutes,
        )
    ]
