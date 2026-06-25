"""调度时间解析工具。

当前只支持项目需要的短格式：30s、30m、2h、1d 和 HH:MM。
"""

from __future__ import annotations

import re
from datetime import time, timedelta

_DURATION_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[smhd])$")


def parse_duration(value: str) -> timedelta:
    """把 30m 这类配置解析为 timedelta。"""

    match = _DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"非法 duration: {value}")
    amount = int(match.group("num"))
    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def parse_clock(value: str) -> time:
    """把 HH:MM 配置解析为 time。"""

    hour_text, minute_text = value.strip().split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))
