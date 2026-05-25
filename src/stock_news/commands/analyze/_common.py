"""analyze 各子命令共用：日期解析 + 目录约定 + 跨阶段加载."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from stock_news.models import ClassifiedMessage, Recommendation


def parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def classified_dir(cfg_data_dir: str, dt: date) -> Path:
    d = Path(cfg_data_dir).expanduser() / dt.isoformat() / "classified"
    d.mkdir(parents=True, exist_ok=True)
    return d


def extracted_dir(cfg_data_dir: str, dt: date) -> Path:
    d = Path(cfg_data_dir).expanduser() / dt.isoformat() / "extracted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def opinion_dir(cfg_data_dir: str, dt: date) -> Path:
    d = Path(cfg_data_dir).expanduser() / dt.isoformat() / "opinions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_classified(cfg_data_dir: str, dt: date) -> list[ClassifiedMessage]:
    path = classified_dir(cfg_data_dir, dt) / "classified.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ClassifiedMessage.model_validate(item) for item in data]


def load_recommendations(cfg_data_dir: str, dt: date) -> list[Recommendation]:
    path = extracted_dir(cfg_data_dir, dt) / "recommendations.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Recommendation.model_validate(item) for item in data]
