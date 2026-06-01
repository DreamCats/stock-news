"""源头雷达：从本地 raw 数据中扫描早期概念/催化候选."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import click

from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import (
    ClassifiedMessage,
    MessageCategory,
    RawMessage,
    Recommendation,
)

TRIGGER_TERMS = (
    "新概念",
    "新方向",
    "新题材",
    "新应用",
    "新场景",
    "进入新阶段",
    "从概念到落地",
    "概念到落地",
    "从0到1",
    "0到1",
    "预期差",
    "拐点",
    "催化",
    "映射",
    "代名词",
    "第二波",
)

STRONG_TRIGGERS = {
    "新概念",
    "新方向",
    "新题材",
    "新应用",
    "新场景",
    "进入新阶段",
    "从概念到落地",
    "概念到落地",
    "从0到1",
    "0到1",
}

NOISE_TERMS = {
    "市场",
    "板块",
    "行业",
    "公司",
    "重点",
    "关注",
    "推荐",
    "策略",
    "观点",
    "复盘",
    "会议",
    "调研",
    "电话会",
    "交流",
    "纪要",
    "团队",
    "证券",
}

NOISE_SUBSTRINGS = (
    "腾讯会议",
    "会议号",
    "密码",
    "报名",
    "联系人",
    "日报",
    "周报",
    "月报",
    "早报",
    "晚报",
    "复盘",
    "路演",
)

THEME_HINTS = (
    "AI",
    "Agent",
    "Token",
    "CPO",
    "SST",
    "算力",
    "商业航天",
    "太空",
    "机器人",
    "低空",
    "芯片",
    "半导体",
    "硅光",
    "光通信",
    "光模块",
    "电力",
    "储能",
    "协同",
    "脑机",
    "固态",
)


@dataclass(frozen=True)
class MessageRow:
    date: date
    message: RawMessage
    category: str | None
    recommendations: tuple[Recommendation, ...]
    terms: tuple[str, ...]
    triggers: tuple[str, ...]


@dataclass(frozen=True)
class Mention:
    term: str
    row: MessageRow
    stocks: tuple[str, ...]


def _parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def _iter_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _available_dates(data_dir: str, end: date) -> list[date]:
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


def _load_classified_map(
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


def _load_recommendation_map(
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


def _normalize_term(term: str) -> str:
    term = term.strip()
    term = re.sub(r"^[#【\[\(（\s]+|[】\]\)）\s]+$", "", term)
    term = re.sub(r"\s+", "", term)
    return term


def _valid_term(term: str) -> bool:
    if not (2 <= len(term) <= 18):
        return False
    if "的最" in term:
        return False
    if term.endswith("战略"):
        return False
    if term in NOISE_TERMS:
        return False
    if any(part in term for part in NOISE_SUBSTRINGS):
        return False
    if re.fullmatch(r"\d{3,}|\d+[Qq]?|[A-Za-z]{1,2}", term):
        return False
    return True


def _looks_like_theme(term: str) -> bool:
    if any(hint in term for hint in THEME_HINTS):
        return True
    if term.endswith(("协同", "产业链", "产业趋势")):
        return True
    return False


def _extract_terms(text: str) -> tuple[str, ...]:
    terms: set[str] = set()

    for match in re.findall(r"#([^#\s，,。；;:：【】\[\]（）()<>《》]{2,24})", text):
        terms.add(_normalize_term(match))

    for title in re.findall(r"【([^】]{2,40})】", text):
        for part in re.split(r"[：:|｜/&、，,\s]+", title):
            part = _normalize_term(part)
            if _looks_like_theme(part):
                terms.add(part)

    explicit_patterns = (
        r"([A-Za-z0-9\u4e00-\u9fff+·\-]{2,18})[，,、\s]*(?:AI|ai)?应用?(?<!最)新概念",
        r"([A-Za-z0-9\u4e00-\u9fff+·\-]{2,18})[，,、\s]*(?<!最)(?:新方向|新题材|新应用|新场景)",
        r"([A-Za-z0-9\u4e00-\u9fff+·\-]{2,18})(?:进入新阶段|从概念到落地|概念到落地)",
    )
    for pattern in explicit_patterns:
        for match in re.findall(pattern, text):
            terms.add(_normalize_term(match))

    suffixes = (
        "协同",
        "新应用",
        "新场景",
        "产业链",
        "产业趋势",
        "商业化",
    )
    suffix_pattern = "|".join(suffixes)
    for match in re.findall(
        rf"([A-Za-z0-9\u4e00-\u9fff+·\-]{{2,14}}(?:{suffix_pattern}))",
        text,
    ):
        terms.add(_normalize_term(match))

    plus_pattern = (
        r"([A-Za-z0-9\u4e00-\u9fff]{1,8}"
        r"\+[A-Za-z0-9\u4e00-\u9fff]{1,8})"
    )
    for match in re.findall(plus_pattern, text):
        term = _normalize_term(match)
        if _looks_like_theme(term):
            terms.add(term)

    return tuple(sorted(term for term in terms if _valid_term(term)))


def _find_triggers(text: str) -> tuple[str, ...]:
    triggers: list[str] = []
    for term in TRIGGER_TERMS:
        for match in re.finditer(re.escape(term), text):
            if match.start() > 0 and text[match.start() - 1] == "最":
                continue
            triggers.append(term)
            break
    return tuple(triggers)


def _stocks_from_recommendations(
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


def _snippet(text: str, limit: int = 80) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _build_rows(
    data_dir: str,
    dates: list[date],
    classified: dict[str, ClassifiedMessage],
    recommendations: dict[str, tuple[Recommendation, ...]],
) -> list[MessageRow]:
    rows: list[MessageRow] = []
    for dt in dates:
        for message in load_messages(data_dir, dt):
            message_recs = recommendations.get(message.message_id, ())
            classified_msg = classified.get(message.message_id)
            category = classified_msg.category.value if classified_msg else None
            rows.append(
                MessageRow(
                    date=dt,
                    message=message,
                    category=category,
                    recommendations=message_recs,
                    terms=_extract_terms(message.raw_content),
                    triggers=_find_triggers(message.raw_content),
                )
            )
    return rows


def _is_source_like(row: MessageRow, start: date, end: date, max_chars: int) -> bool:
    if not (start <= row.date <= end):
        return False
    if row.message.source != "个人群":
        return False
    if len(row.message.raw_content) > max_chars:
        return False
    if not row.triggers:
        return False
    if not row.terms:
        return False
    if row.recommendations:
        return False
    return row.category in {
        MessageCategory.RESEARCH.value,
        MessageCategory.EVENT.value,
        MessageCategory.NOISE.value,
        None,
    }


def _score_candidate(
    first: Mention,
    previous_count: int,
    later_mentions: list[Mention],
    stock_mentions: list[Mention],
) -> float:
    row = first.row
    score = 8.0
    score += 5.0 if len(row.message.raw_content) <= 120 else 2.0
    score += 6.0 if any(trigger in STRONG_TRIGGERS for trigger in row.triggers) else 2.0
    if row.category in {MessageCategory.RESEARCH.value, MessageCategory.EVENT.value}:
        score += 4.0
    if previous_count == 0:
        score += 10.0
    elif previous_count <= 2:
        score += 5.0
    else:
        score -= min(previous_count, 12) * 0.8

    later_groups = {
        m.row.message.group_name for m in later_mentions if m.row.message.group_name
    }
    later_senders = {m.row.message.sender for m in later_mentions}
    later_dates = {m.row.date for m in later_mentions}
    score += min(len(later_mentions), 12) * 0.6
    score += min(len(later_groups), 5) * 1.2
    score += min(len(later_senders), 5) * 1.0
    score += min(len(later_dates), 5) * 1.2

    if stock_mentions:
        score += 6.0
        score += min(sum(len(m.stocks) for m in stock_mentions), 10) * 0.5
    return round(score, 1)


def _novelty_level(previous_count: int) -> str:
    if previous_count == 0:
        return "全新"
    if previous_count <= 2:
        return "低频"
    if previous_count <= 20:
        return "已有"
    return "高频旧主题"


def _signal_type(
    previous_count: int,
    later_mentions: list[Mention],
    stock_mentions: list[Mention],
) -> str:
    if previous_count == 0:
        return "新词源头"
    if previous_count <= 2:
        return "低频新线索"
    if stock_mentions and len(later_mentions) >= 3:
        return "扩散带股"
    if previous_count > 20 and len(later_mentions) >= 5:
        return "旧主题再催化"
    return "普通线索"


def _signal_priority(signal_type: str) -> int:
    priorities = {
        "新词源头": 0,
        "低频新线索": 1,
        "扩散带股": 2,
        "旧主题再催化": 3,
        "普通线索": 4,
    }
    return priorities.get(signal_type, 9)


def _evidence(candidate: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    previous = int(candidate["previous_mentions"])
    later = int(candidate["later_mentions"])
    if previous == 0:
        evidence.append("本地历史首次出现")
    elif previous <= 2:
        evidence.append(f"历史低频，仅 {previous} 次")
    else:
        evidence.append(f"历史已有 {previous} 次")
    if later:
        evidence.append(
            "后续扩散 "
            f"{later} 次/{candidate['later_days']} 天/"
            f"{candidate['later_groups']} 群/{candidate['later_senders']} 人"
        )
    if candidate["first_stock"] is not None:
        evidence.append("后续出现带股消息")
    return evidence


def _candidate_to_dict(candidate: dict[str, Any]) -> dict[str, Any]:
    first = candidate["first"]
    first_stock = candidate["first_stock"]
    return {
        "term": candidate["term"],
        "score": candidate["score"],
        "signal_type": candidate["signal_type"],
        "novelty_level": candidate["novelty_level"],
        "previous_mentions": candidate["previous_mentions"],
        "later_mentions": candidate["later_mentions"],
        "later_days": candidate["later_days"],
        "later_groups": candidate["later_groups"],
        "later_senders": candidate["later_senders"],
        "evidence": _evidence(candidate),
        "features": {
            "message_chars": len(first.row.message.raw_content),
            "trigger_count": len(first.row.triggers),
            "has_strong_trigger": any(
                trigger in STRONG_TRIGGERS for trigger in first.row.triggers
            ),
            "has_stock_later": first_stock is not None,
            "source": first.row.message.source,
            "category": first.row.category,
        },
        "first": {
            "time": first.row.message.message_time.isoformat(),
            "group": first.row.message.group_name,
            "sender": first.row.message.sender,
            "message_id": first.row.message.message_id,
            "category": first.row.category,
            "triggers": list(first.row.triggers),
            "snippet": _snippet(first.row.message.raw_content),
        },
        "first_stock": None
        if first_stock is None
        else {
            "time": first_stock.row.message.message_time.isoformat(),
            "group": first_stock.row.message.group_name,
            "sender": first_stock.row.message.sender,
            "message_id": first_stock.row.message.message_id,
            "stocks": list(first_stock.stocks[:10]),
            "snippet": _snippet(first_stock.row.message.raw_content),
        },
        "stock_names": candidate["stock_names"],
    }


def _format_plain(candidates: list[dict[str, Any]], start: date, end: date) -> None:
    if not candidates:
        click.echo(f"{start} 到 {end} 未发现源头候选")
        return

    click.echo(f"{start} 到 {end} 源头候选 TOP {len(candidates)}:\n")
    for index, candidate in enumerate(candidates, start=1):
        first = candidate["first"]
        first_stock = candidate["first_stock"]
        click.echo(
            f"{index}. {candidate['term']}  score={candidate['score']}  "
            f"信号={candidate['signal_type']}  新鲜度={candidate['novelty_level']}"
        )
        click.echo(
            "   计数: "
            f"历史提及={candidate['previous_mentions']}，"
            f"后续扩散={candidate['later_mentions']}，"
            f"覆盖={candidate['later_days']}天/"
            f"{candidate['later_groups']}群/{candidate['later_senders']}人"
        )
        click.echo(
            "   首次: "
            f"{first.row.message.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"{first.row.message.group_name or '-'} / {first.row.message.sender}"
        )
        click.echo(
            f"   形态: {first.row.category or '-'}，"
            f"触发={','.join(first.row.triggers)}，"
            f"message_id={first.row.message.message_id}"
        )
        evidence = "；".join(_evidence(candidate))
        if evidence:
            click.echo(f"   依据: {evidence}")
        click.echo(f"   摘要: {_snippet(first.row.message.raw_content)}")
        if first_stock is None:
            click.echo("   首次带股: 未发现")
        else:
            stocks = "、".join(first_stock.stocks[:8])
            click.echo(
                "   首次带股: "
                f"{first_stock.row.message.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"{first_stock.row.message.group_name or '-'} / {stocks}"
            )
        click.echo()


def scan_sources(
    start_str: str,
    end_str: str,
    lookahead_days: int,
    top: int,
    max_message_chars: int,
    json_output: bool,
) -> None:
    """扫描本地 raw 数据中的源头候选，不调用外部 API，不写文件."""
    cfg = load()
    start = _parse_date(start_str)
    end = _parse_date(end_str)
    if end < start:
        raise click.ClickException("结束日期不能早于开始日期")

    observe_end = end + timedelta(days=lookahead_days)
    dates = _available_dates(cfg.storage.data_dir, observe_end)
    if not dates:
        raise click.ClickException("未找到本地数据目录")

    classified = _load_classified_map(cfg.storage.data_dir, dates)
    recommendations = _load_recommendation_map(cfg.storage.data_dir, dates)
    rows = _build_rows(cfg.storage.data_dir, dates, classified, recommendations)

    mentions_by_term: dict[str, list[Mention]] = defaultdict(list)
    for row in rows:
        stocks = _stocks_from_recommendations(row.recommendations)
        for term in row.terms:
            mentions_by_term[term].append(Mention(term=term, row=row, stocks=stocks))

    candidate_by_term: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _is_source_like(row, start, end, max_message_chars):
            continue
        for term in row.terms:
            mentions = sorted(
                mentions_by_term[term],
                key=lambda item: (
                    item.row.message.message_time,
                    item.row.message.message_id,
                ),
            )
            current_time = row.message.message_time
            previous = [
                m for m in mentions if m.row.message.message_time < current_time
            ]
            later = [m for m in mentions if m.row.message.message_time > current_time]
            stock_mentions = [m for m in later if m.stocks]
            first = Mention(
                term=term,
                row=row,
                stocks=_stocks_from_recommendations(row.recommendations),
            )
            score = _score_candidate(first, len(previous), later, stock_mentions)
            signal_type = _signal_type(len(previous), later, stock_mentions)
            signal_priority = _signal_priority(signal_type)
            existing = candidate_by_term.get(term)
            if existing is not None and (
                int(existing["signal_priority"]) < signal_priority
                or (
                    int(existing["signal_priority"]) == signal_priority
                    and float(existing["score"]) >= score
                )
            ):
                continue
            stock_names = sorted(
                {stock for mention in stock_mentions for stock in mention.stocks}
            )
            candidate_by_term[term] = {
                "term": term,
                "score": score,
                "signal_type": signal_type,
                "signal_priority": signal_priority,
                "novelty_level": _novelty_level(len(previous)),
                "previous_mentions": len(previous),
                "later_mentions": len(later),
                "later_days": len({m.row.date for m in later}),
                "later_groups": len(
                    {
                        m.row.message.group_name
                        for m in later
                        if m.row.message.group_name
                    }
                ),
                "later_senders": len({m.row.message.sender for m in later}),
                "first": first,
                "first_stock": stock_mentions[0] if stock_mentions else None,
                "stock_names": stock_names[:12],
            }

    candidates = sorted(
        candidate_by_term.values(),
        key=lambda item: (
            int(item["signal_priority"]),
            -float(item["score"]),
            int(item["previous_mentions"]),
            str(item["first"].row.message.message_time),
        ),
    )[:top]

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "lookahead_days": lookahead_days,
                        "scanned_messages": len(rows),
                        "candidate_count": len(candidate_by_term),
                        "candidates": [_candidate_to_dict(item) for item in candidates],
                    },
                    "message": f"发现 {len(candidate_by_term)} 个源头候选",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _format_plain(candidates, start, end)
