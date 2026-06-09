"""每日晚报时间解析与展示."""

from __future__ import annotations

from datetime import datetime, time, timedelta


def parse_datetime_expr(value: str, now: datetime | None = None) -> datetime:
    """解析晚报时间表达式."""
    base = now or datetime.now()
    normalized = value.strip()
    for prefix, day in (
        ("today-", base.date()),
        ("yesterday-", base.date() - timedelta(days=1)),
    ):
        if normalized.startswith(prefix):
            clock = _parse_clock(normalized[len(prefix) :])
            return datetime.combine(day, clock)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(
        "时间格式非法，支持 today-21:00、yesterday-15:00、"
        "YYYY-MM-DD HH:MM 或 YYYY-MM-DDTHH:MM"
    )


def display_dt(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def _parse_clock(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"非法时间格式，期望 HH:MM: {value}") from exc
