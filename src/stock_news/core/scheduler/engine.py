"""调度触发判断。

这里只判断某个任务在当前时间是否应该触发，不负责执行任务。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta


def is_interval_due(
    *,
    now: datetime,
    every: timedelta,
    last_started_at: datetime | None,
) -> bool:
    """判断 interval 任务是否到期。"""

    if last_started_at is None:
        return True
    return now - last_started_at >= every


def is_daily_due(
    *,
    now: datetime,
    at: time,
    last_started_at: datetime | None,
) -> bool:
    """判断每天固定时间任务是否到期。"""

    if now.time() < at:
        return False
    if last_started_at is None:
        return True
    return last_started_at.date() != now.date()
