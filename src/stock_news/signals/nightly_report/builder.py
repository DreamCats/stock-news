"""每日晚报生成编排."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_news.commands.strategy.payload import _build_candidate_trades
from stock_news.commands.strategy.scoring import _build_consensus
from stock_news.commands.strategy.storage import _load_sender_stats
from stock_news.signals.nightly_report.llm import attach_boss_lines
from stock_news.signals.nightly_report.material import build_nightly_items
from stock_news.signals.nightly_report.models import NightlyOutput
from stock_news.signals.nightly_report.render import render_nightly_html
from stock_news.signals.nightly_report.storage import load_recommendations_range


def generate_nightly_report(
    data_dir: str,
    start: datetime,
    end: datetime,
    top: int = 16,
    *,
    candidate_top: int | None = None,
    use_llm: bool = False,
    provider_name: str | None = None,
    generated_at: datetime | None = None,
    html_out: Path | None = None,
    json_out: Path | None = None,
) -> NightlyOutput:
    """从 recommend 数据生成每日晚报 JSON 和 HTML."""
    if start >= end:
        raise ValueError("开始时间必须早于结束时间")
    if top <= 0:
        raise ValueError("top 必须大于 0")
    candidate_limit = max(candidate_top or top, top)

    recs = load_recommendations_range(data_dir, start.date(), end.date())
    window_recs = [
        rec
        for rec in recs
        if rec.message_time is not None and start <= rec.message_time <= end
    ]
    stock_recs = [rec for rec in window_recs if (rec.target_type or "stock") == "stock"]
    sender_stats = _load_sender_stats(data_dir)
    consensus_all = _build_consensus(stock_recs, sender_stats, None)
    candidates = _build_candidate_trades(consensus_all, [], candidate_limit)

    payload: dict[str, Any] = {
        "report_type": "nightly",
        "generated_at": (generated_at or datetime.now()).isoformat(timespec="seconds"),
        "window": {
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
        },
        "stats": {
            "recommendations": len(recs),
            "window_recommendations": len(window_recs),
            "window_stock_recommendations": len(stock_recs),
            "candidates": len(candidates),
            "final_items": 0,
        },
        "candidate_trades": candidates,
        "sender_stats": {
            sender: sender_stats[sender]
            for item in candidates
            for sender in item.get("senders", [])
            if sender in sender_stats
        },
    }
    out_dir = Path(data_dir).expanduser() / end.date().isoformat() / "nightly"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload["items"] = build_nightly_items(payload, stock_recs)
    attach_boss_lines(
        payload,
        use_llm,
        provider_name,
        final_top=top,
        batch_dir=out_dir / "llm_batches",
    )
    payload["stats"]["final_items"] = len(payload.get("items") or [])

    json_path = json_out.expanduser() if json_out else out_dir / "nightly.json"
    html_path = html_out.expanduser() if html_out else out_dir / "nightly.html"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    html_path.write_text(render_nightly_html(payload), encoding="utf-8")
    return NightlyOutput(payload=payload, json_path=json_path, html_path=html_path)
