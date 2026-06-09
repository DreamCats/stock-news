"""每日晚报本地数据读取."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from stock_news.models import Recommendation


def load_recommendations_range(
    data_dir: str,
    start: date,
    end: date,
) -> list[Recommendation]:
    out: list[Recommendation] = []
    root = Path(data_dir).expanduser()
    current = start
    while current <= end:
        path = root / current.isoformat() / "extracted" / "recommendations.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                out.extend(Recommendation.model_validate(item) for item in data)
        current += timedelta(days=1)
    return out
