from __future__ import annotations

import importlib
from datetime import datetime

from stock_news.models import RawMessage, Recommendation

extract_mod = importlib.import_module("stock_news.commands.analyze.extract")


def _raw_message(content: str = "继续强推国产算力") -> RawMessage:
    return RawMessage(
        source="个人消息",
        sender="张三",
        message_time=datetime(2026, 5, 25, 9, 1),
        raw_content=content,
        fetch_time=datetime(2026, 5, 25, 9, 1),
        fetch_window="20260525090000_20260525092000",
    )


def test_recommendation_from_item_normalizes_target_and_action() -> None:
    msg = _raw_message()

    rec = extract_mod._recommendation_from_item(
        msg,
        {
            "target_type": "theme",
            "target_name": "国产算力",
            "ticker": None,
            "market": "A股/港股",
            "action": "强推",
            "strength": "高",
            "horizon": "波段",
            "reasoning": "国产基础资源链重估",
            "risk_note": None,
            "confidence": 1.4,
            "evidence": "继续强推国产算力",
        },
    )

    assert rec is not None
    assert rec.target_type == "theme"
    assert rec.target_name == "国产算力"
    assert rec.ticker == "国产算力"
    assert rec.market is None
    assert rec.raw_action == "强推"
    assert rec.normalized_action == "买入"
    assert rec.action == "买入"
    assert rec.confidence == 1.0
    assert rec.evidence == "继续强推国产算力"


def test_legacy_recommendation_fills_new_fields() -> None:
    msg = _raw_message("关注寒武纪")

    rec = Recommendation(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        ticker="寒武纪",
        action="关注",
        strength="中",
        raw_content=msg.raw_content,
    )

    assert rec.target_type == "stock"
    assert rec.target_name == "寒武纪"
    assert rec.raw_action == "关注"
    assert rec.normalized_action == "关注"
    assert rec.confidence == 0.8
