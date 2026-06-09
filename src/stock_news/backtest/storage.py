"""推荐回测本地存储."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from stock_news.backtest.summary import aggregate_by_sender
from stock_news.models import Recommendation


def load_recommendations(data_dir: str, dt: date) -> list[Recommendation]:
    path = (
        Path(data_dir).expanduser()
        / dt.isoformat()
        / "extracted"
        / "recommendations.json"
    )
    if not path.exists():
        return []
    return [
        Recommendation.model_validate(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


def result_key_from_rec(rec: Recommendation) -> tuple[str, ...]:
    return ("rec", rec.message_id, rec.ticker, rec.action)


def legacy_result_key_from_rec(rec: Recommendation) -> tuple[str, ...]:
    rec_date = rec.message_time.strftime("%Y%m%d") if rec.message_time else ""
    return ("legacy", rec.sender, rec.ticker, rec.action, rec_date)


def result_key_from_result(item: dict[str, Any]) -> tuple[str, ...]:
    message_id = item.get("message_id")
    ticker = item.get("ticker")
    action = item.get("action")
    if message_id and ticker and action:
        return ("rec", str(message_id), str(ticker), str(action))
    if message_id:
        return ("message_id", str(message_id))
    return (
        "legacy",
        str(item.get("sender", "")),
        str(item.get("ticker", "")),
        str(item.get("action", "")),
        str(item.get("rec_date", "")),
    )


def load_backtest_results(data_dir: str, dt: date) -> list[dict[str, Any]]:
    path = Path(data_dir).expanduser() / dt.isoformat() / "backtest" / "results.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_backtest_results(
    data_dir: str,
    dt: date,
    results: list[dict[str, Any]],
) -> None:
    out_dir = Path(data_dir).expanduser() / dt.isoformat() / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sender_stats = aggregate_by_sender(results)
    stats_path = out_dir / "sender_stats.json"
    stats_path.write_text(
        json.dumps(sender_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def result_with_rec_identity(
    result: dict[str, Any],
    rec: Recommendation,
    ts_code: str,
    rec_date: str,
) -> dict[str, Any]:
    return {
        **result,
        "message_id": rec.message_id,
        "ts_code": ts_code,
        "ticker": rec.ticker,
        "sender": rec.sender,
        "action": rec.action,
        "strength": rec.strength,
        "rec_date": rec_date,
    }
