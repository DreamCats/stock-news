from __future__ import annotations

import json
from datetime import datetime

from stock_news.models import Recommendation


def write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def rec(
    message_id: str,
    message_time: datetime,
    target_type: str = "stock",
    target_name: str = "寒武纪",
    sender: str = "张三",
    evidence: str = "算力订单改善",
) -> Recommendation:
    return Recommendation(
        message_id=message_id,
        sender=sender,
        message_time=message_time,
        target_type=target_type,
        target_name=target_name,
        ticker="寒武纪",
        action="买入",
        strength="强",
        confidence=0.9,
        evidence=evidence,
        reasoning=evidence,
        risk_note="短期涨幅较大",
        raw_content="寒武纪算力订单改善，关注",
    )
