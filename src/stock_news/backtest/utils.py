"""推荐回测通用工具."""

from __future__ import annotations

from datetime import date, timedelta


def parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def is_bullish(action: str) -> bool:
    return action in ("买入", "加仓", "关注")
