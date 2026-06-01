"""源头雷达扫描编排."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from stock_news.common.storage import load_messages
from stock_news.models import ClassifiedMessage, Recommendation
from stock_news.source.features import (
    extract_terms,
    find_triggers,
    is_source_like,
    novelty_level,
    score_candidate,
    signal_priority,
    signal_type,
    stocks_from_recommendations,
)
from stock_news.source.models import (
    Mention,
    MessageRow,
    SourceCandidate,
    SourceScanResult,
)


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


def build_rows(
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
                    terms=extract_terms(message.raw_content),
                    triggers=find_triggers(message.raw_content),
                )
            )
    return rows


def scan_source_candidates(
    data_dir: str,
    start: date,
    end: date,
    lookahead_days: int,
    top: int,
    max_message_chars: int,
) -> SourceScanResult:
    observe_end = end + timedelta(days=lookahead_days)
    dates = available_dates(data_dir, observe_end)
    if not dates:
        raise ValueError("未找到本地数据目录")

    classified = load_classified_map(data_dir, dates)
    recommendations = load_recommendation_map(data_dir, dates)
    rows = build_rows(data_dir, dates, classified, recommendations)

    mentions_by_term: dict[str, list[Mention]] = defaultdict(list)
    for row in rows:
        stocks = stocks_from_recommendations(row.recommendations)
        for term in row.terms:
            mentions_by_term[term].append(Mention(term=term, row=row, stocks=stocks))

    candidate_by_term: dict[str, SourceCandidate] = {}
    for row in rows:
        if not is_source_like(row, start, end, max_message_chars):
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
                stocks=stocks_from_recommendations(row.recommendations),
            )
            score = score_candidate(first, len(previous), later, stock_mentions)
            signal = signal_type(len(previous), later, stock_mentions)
            priority = signal_priority(signal)
            existing = candidate_by_term.get(term)
            if existing is not None and (
                existing.signal_priority < priority
                or (existing.signal_priority == priority and existing.score >= score)
            ):
                continue
            stock_names = sorted(
                {stock for mention in stock_mentions for stock in mention.stocks}
            )
            candidate_by_term[term] = SourceCandidate(
                term=term,
                score=score,
                signal_type=signal,
                signal_priority=priority,
                novelty_level=novelty_level(len(previous)),
                previous_mentions=len(previous),
                later_mentions=len(later),
                later_days=len({m.row.date for m in later}),
                later_groups=len(
                    {
                        m.row.message.group_name
                        for m in later
                        if m.row.message.group_name
                    }
                ),
                later_senders=len({m.row.message.sender for m in later}),
                first=first,
                first_stock=stock_mentions[0] if stock_mentions else None,
                stock_names=tuple(stock_names[:12]),
            )

    candidates = sorted(
        candidate_by_term.values(),
        key=lambda item: (
            item.signal_priority,
            -item.score,
            item.previous_mentions,
            item.first.row.message.message_time,
        ),
    )[:top]
    return SourceScanResult(
        start=start,
        end=end,
        lookahead_days=lookahead_days,
        scanned_messages=len(rows),
        candidate_count=len(candidate_by_term),
        candidates=tuple(candidates),
    )
