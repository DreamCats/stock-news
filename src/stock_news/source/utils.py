"""源头雷达本地数据读取工具."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from stock_news.models import ClassifiedMessage, Recommendation


def parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def available_dates(data_dir: str, end: date) -> list[date]:
    root = Path(data_dir).expanduser()
    dates: list[date] = []
    if not root.exists():
        return dates
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            dt = date.fromisoformat(path.name)
        except ValueError:
            continue
        if dt <= end:
            dates.append(dt)
    return sorted(dates)


def load_classified_map(
    data_dir: str, dates: list[date]
) -> dict[str, ClassifiedMessage]:
    out: dict[str, ClassifiedMessage] = {}
    root = Path(data_dir).expanduser()
    for dt in dates:
        path = root / dt.isoformat() / "classified" / "classified.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data:
            try:
                msg = ClassifiedMessage.model_validate(item)
            except Exception:
                continue
            out[msg.message_id] = msg
    return out


def load_recommendation_map(
    data_dir: str, dates: list[date]
) -> dict[str, tuple[Recommendation, ...]]:
    grouped: dict[str, list[Recommendation]] = defaultdict(list)
    root = Path(data_dir).expanduser()
    for dt in dates:
        path = root / dt.isoformat() / "extracted" / "recommendations.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data:
            try:
                rec = Recommendation.model_validate(item)
            except Exception:
                continue
            grouped[rec.message_id].append(rec)
    return {message_id: tuple(items) for message_id, items in grouped.items()}


def stocks_from_recommendations(
    recommendations: tuple[Recommendation, ...],
) -> tuple[str, ...]:
    stocks: list[str] = []
    for rec in recommendations:
        if rec.target_type != "stock":
            continue
        name = (rec.target_name or rec.ticker or "").strip()
        if name and name not in stocks:
            stocks.append(name)
    return tuple(stocks)


def snippet(text: str, limit: int = 80) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
