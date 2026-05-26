"""盘中策略快报生成."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import click

from stock_news.commands.analyze._common import (
    load_recommendations,
    parse_date,
)
from stock_news.common.config import load
from stock_news.models import OpinionNode, Recommendation

BULLISH_ACTIONS = {"买入", "加仓", "关注"}
BEARISH_ACTIONS = {"卖出", "减仓", "回避"}
STRENGTH_SCORE = {
    "强": 18,
    "高": 18,
    "strong": 18,
    "中": 10,
    "medium": 10,
    "弱": 4,
    "低": 4,
    "low": 4,
}


def _date_dir(data_dir: str, dt_str: str) -> Path:
    return Path(data_dir).expanduser() / dt_str


def _strategy_dir(data_dir: str, dt_str: str) -> Path:
    d = _date_dir(data_dir, dt_str) / "strategy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_opinions(data_dir: str, dt_str: str) -> list[OpinionNode]:
    path = _date_dir(data_dir, dt_str) / "opinions" / "opinions.json"
    data = _load_json(path, [])
    if not isinstance(data, list):
        return []
    return [OpinionNode.model_validate(item) for item in data]


def _load_sender_stats(data_dir: str) -> dict[str, dict[str, Any]]:
    path = Path(data_dir).expanduser() / "backtest_summary" / "sender_stats.json"
    data = _load_json(path, [])
    if not isinstance(data, list):
        return {}
    return {
        str(item.get("sender")): item
        for item in data
        if isinstance(item, dict) and item.get("sender")
    }


def _load_state(data_dir: str, dt_str: str) -> dict[str, Any]:
    data = _load_json(_strategy_dir(data_dir, dt_str) / "state.json", {})
    return data if isinstance(data, dict) else {}


def _save_outputs(
    data_dir: str,
    dt_str: str,
    payload: dict[str, Any],
    markdown: str,
    state: dict[str, Any],
) -> tuple[Path, Path]:
    out_dir = _strategy_dir(data_dir, dt_str)
    json_path = out_dir / "strategy.json"
    md_path = out_dir / "strategy.md"
    state_path = out_dir / "state.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path, md_path


def _opinion_key(opinion: OpinionNode) -> str:
    return f"{opinion.opinion_id}:{opinion.version}:{opinion.message_id}"


def _rec_time(rec: Recommendation, fallback: datetime) -> datetime:
    return rec.message_time or fallback


def _sender_quality(sender: str, sender_stats: dict[str, dict[str, Any]]) -> float:
    stat = sender_stats.get(sender, {})
    count = int(stat.get("count") or 0)
    win_rate = float(stat.get("win_rate_t5") or 0)
    excess = float(stat.get("avg_excess_t5") or 0)
    sample_score = min(count, 10) * 1.5
    return win_rate * 30 + sample_score + excess * 100


def _strength_score(strength: str) -> float:
    return float(STRENGTH_SCORE.get(strength, 8))


def _action_side(action: str) -> str:
    if action in BULLISH_ACTIONS:
        return "bullish"
    if action in BEARISH_ACTIONS:
        return "bearish"
    return "neutral"


def _short_text(text: str | None, max_len: int = 80) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact if len(compact) <= max_len else compact[: max_len - 1] + "..."


def _build_recommendation_item(
    rec: Recommendation,
    sender_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stat = sender_stats.get(rec.sender, {})
    return {
        "message_id": rec.message_id,
        "ticker": rec.ticker,
        "action": rec.action,
        "strength": rec.strength,
        "sender": rec.sender,
        "message_time": rec.message_time.isoformat() if rec.message_time else None,
        "reasoning": _short_text(rec.reasoning),
        "risk_note": _short_text(rec.risk_note),
        "sender_30d": {
            "count": stat.get("count"),
            "win_rate_t5": stat.get("win_rate_t5"),
            "avg_ret_t5": stat.get("avg_ret_t5"),
            "avg_excess_t5": stat.get("avg_excess_t5"),
        },
    }


def _build_consensus(
    recs: list[Recommendation],
    sender_stats: dict[str, dict[str, Any]],
    top: int,
) -> list[dict[str, Any]]:
    by_ticker: dict[str, list[Recommendation]] = {}
    for rec in recs:
        by_ticker.setdefault(rec.ticker, []).append(rec)

    items: list[dict[str, Any]] = []
    for ticker, ticker_recs in by_ticker.items():
        senders = sorted({r.sender for r in ticker_recs})
        actions = Counter(r.action for r in ticker_recs)
        latest = max(
            (_rec_time(r, datetime.min) for r in ticker_recs),
            default=datetime.min,
        )
        avg_quality = sum(
            _sender_quality(r.sender, sender_stats) for r in ticker_recs
        ) / len(ticker_recs)
        strength = max(_strength_score(r.strength) for r in ticker_recs)
        score = round(len(senders) * 20 + avg_quality + strength, 2)
        reasons = [
            _short_text(r.reasoning)
            for r in ticker_recs
            if _short_text(r.reasoning)
        ][:3]
        risks = [
            _short_text(r.risk_note)
            for r in ticker_recs
            if _short_text(r.risk_note)
        ][:3]
        items.append(
            {
                "ticker": ticker,
                "score": score,
                "senders": senders,
                "recommendation_count": len(ticker_recs),
                "actions": dict(actions),
                "latest_time": latest.isoformat() if latest != datetime.min else None,
                "reasons": reasons,
                "risks": risks,
            }
        )

    return sorted(items, key=lambda item: item["score"], reverse=True)[:top]


def _build_opinion_changes(
    opinions: list[OpinionNode],
    seen_opinion_keys: set[str],
    top: int,
) -> list[dict[str, Any]]:
    changed_types = {"new", "reinforce", "revise", "reverse", "withdraw"}
    changes = [
        opinion
        for opinion in opinions
        if _opinion_key(opinion) not in seen_opinion_keys
        and opinion.update_type in changed_types
    ]
    return [
        {
            "key": _opinion_key(opinion),
            "sender": opinion.sender,
            "topic_key": opinion.topic_key,
            "stance": opinion.stance,
            "update_type": opinion.update_type,
            "summary": opinion.summary,
            "message_id": opinion.message_id,
        }
        for opinion in changes[-top:]
    ]


def _build_conflicts(
    recs: list[Recommendation],
    opinions: list[OpinionNode],
    top: int,
) -> list[dict[str, Any]]:
    by_ticker: dict[str, set[str]] = {}
    for rec in recs:
        by_ticker.setdefault(rec.ticker, set()).add(_action_side(rec.action))
    for opinion in opinions:
        by_ticker.setdefault(opinion.topic_key, set()).add(opinion.stance)

    conflicts = []
    for ticker, sides in by_ticker.items():
        if "bullish" in sides and "bearish" in sides:
            conflicts.append({"ticker": ticker, "sides": sorted(sides)})
    return conflicts[:top]


def _build_candidate_trades(
    consensus: list[dict[str, Any]],
    opinion_changes: list[dict[str, Any]],
    top: int,
) -> list[dict[str, Any]]:
    changes_by_topic: dict[str, list[dict[str, Any]]] = {}
    for change in opinion_changes:
        changes_by_topic.setdefault(str(change["topic_key"]), []).append(change)

    candidates = []
    for item in consensus[:top]:
        why = [f"{item['recommendation_count']} 条推荐"]
        if len(item["senders"]) > 1:
            why.append(f"{len(item['senders'])} 位推荐人共识")
        changes = changes_by_topic.get(str(item["ticker"]), [])
        if changes:
            why.extend(f"观点 {c['update_type']}" for c in changes[:2])
        candidates.append(
            {
                "ticker": item["ticker"],
                "score": item["score"],
                "why_selected": why,
                "reasons": item["reasons"],
                "risks": item["risks"],
                "senders": item["senders"],
            }
        )
    return candidates


def _build_payload(
    data_dir: str,
    date_str: str,
    window_minutes: int,
    top: int,
    report_time: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    dt = parse_date(date_str)
    dt_str = dt.isoformat()
    window_start = report_time - timedelta(minutes=window_minutes)

    recs = load_recommendations(data_dir, dt)
    opinions = _load_opinions(data_dir, dt_str)
    sender_stats = _load_sender_stats(data_dir)
    state = _load_state(data_dir, dt_str)
    seen_message_ids = set(state.get("message_ids") or [])
    seen_opinion_keys = set(state.get("opinion_keys") or [])

    first_run = not seen_message_ids and not seen_opinion_keys
    new_recs = [
        rec
        for rec in recs
        if rec.message_id not in seen_message_ids
        and (not first_run or _rec_time(rec, report_time) >= window_start)
    ]

    new_rec_ids = {rec.message_id for rec in new_recs}
    opinion_changes = _build_opinion_changes(opinions, seen_opinion_keys, top)
    if first_run:
        opinion_changes = [
            item for item in opinion_changes if item["message_id"] in new_rec_ids
        ]

    consensus = _build_consensus(new_recs, sender_stats, top)
    conflicts = _build_conflicts(new_recs, opinions, top)
    candidates = _build_candidate_trades(consensus, opinion_changes, top)
    involved_senders = sorted({rec.sender for rec in new_recs})
    involved_stats = {
        sender: sender_stats[sender]
        for sender in involved_senders
        if sender in sender_stats
    }

    payload = {
        "report_time": report_time.isoformat(timespec="seconds"),
        "date": dt_str,
        "window": {
            "minutes": window_minutes,
            "start": window_start.isoformat(timespec="seconds"),
            "end": report_time.isoformat(timespec="seconds"),
        },
        "has_updates": bool(new_recs or opinion_changes),
        "new_recommendations": [
            _build_recommendation_item(rec, sender_stats) for rec in new_recs
        ],
        "top_consensus": consensus,
        "opinion_changes": opinion_changes,
        "conflicts": conflicts,
        "sender_stats": involved_stats,
        "candidate_trades": candidates,
    }
    next_state = {
        "generated_at": report_time.isoformat(timespec="seconds"),
        "message_ids": sorted(seen_message_ids | {rec.message_id for rec in recs}),
        "opinion_keys": sorted(seen_opinion_keys | {_opinion_key(o) for o in opinions}),
    }
    return payload, next_state


def _pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "/").replace("\n", " ")


def _render_markdown(payload: dict[str, Any]) -> str:
    report_time = datetime.fromisoformat(str(payload["report_time"]))
    lines = [f"# 盘中投研快报 {report_time.strftime('%H:%M')}", ""]

    candidates = payload["candidate_trades"]
    lines.append("## 结论")
    if candidates:
        for item in candidates[:3]:
            why = "、".join(item["why_selected"])
            lines.append(f"- {item['ticker']}：{why}，score={item['score']}")
    else:
        lines.append("- 本轮暂无新增有效机会。")

    lines.extend(["", "## 新增机会"])
    lines.append("| 标的 | 动作 | 推荐人 | 30d T+5胜率 | 样本 | 核心理由 | 风险 |")
    lines.append("| --- | --- | --- | ---: | ---: | --- | --- |")
    for rec in payload["new_recommendations"]:
        stat = rec["sender_30d"]
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(rec["ticker"]),
                    _cell(rec["action"]),
                    _cell(rec["sender"]),
                    _pct(stat.get("win_rate_t5")),
                    _cell(stat.get("count")),
                    _cell(rec.get("reasoning")),
                    _cell(rec.get("risk_note")),
                ]
            )
            + " |"
        )
    if not payload["new_recommendations"]:
        lines.append("| - | - | - | - | - | 本轮无新增推荐 | - |")

    lines.extend(["", "## 共识增强"])
    if payload["top_consensus"]:
        for item in payload["top_consensus"]:
            senders = "、".join(item["senders"])
            lines.append(f"- {item['ticker']}：{senders}，score={item['score']}")
    else:
        lines.append("- 本轮暂无多人共识。")

    lines.extend(["", "## 观点变化"])
    if payload["opinion_changes"]:
        for item in payload["opinion_changes"]:
            lines.append(
                f"- [{item['update_type']}][{item['stance']}] "
                f"{item['sender']} -> {item['topic_key']}：{item['summary']}"
            )
    else:
        lines.append("- 本轮暂无显著观点变化。")

    lines.extend(["", "## 推荐人可信度"])
    if payload["sender_stats"]:
        for sender, stat in payload["sender_stats"].items():
            lines.append(
                f"- {sender}：样本 {stat.get('count', '-')}，"
                f"T+5 胜率 {_pct(stat.get('win_rate_t5'))}，"
                f"平均超额 {_pct(stat.get('avg_excess_t5'))}"
            )
    else:
        lines.append("- 本轮涉及推荐人暂无 30d 回测样本。")

    lines.extend(["", "## 原始线索"])
    for rec in payload["new_recommendations"][:5]:
        clue = rec.get("reasoning") or rec.get("risk_note") or "-"
        lines.append(f"- {rec['ticker']} / {rec['sender']}：{clue}")
    if not payload["new_recommendations"]:
        lines.append("- 无。")

    return "\n".join(lines) + "\n"


def generate(
    date_str: str,
    window_minutes: int,
    top: int,
    json_output: bool,
) -> None:
    """生成盘中策略快报 JSON 和 Markdown."""
    cfg = load()
    report_time = datetime.now().replace(microsecond=0)
    payload, state = _build_payload(
        cfg.storage.data_dir,
        date_str,
        window_minutes,
        top,
        report_time,
    )
    markdown = _render_markdown(payload)
    json_path, md_path = _save_outputs(
        cfg.storage.data_dir,
        payload["date"],
        payload,
        markdown,
        state,
    )

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": payload["date"],
                        "has_updates": payload["has_updates"],
                        "json_path": str(json_path),
                        "markdown_path": str(md_path),
                    },
                },
                ensure_ascii=False,
            )
        )
    else:
        click.echo(f"策略快报已生成: {md_path}")
        if not payload["has_updates"]:
            click.echo("本轮无新增有效机会。")
