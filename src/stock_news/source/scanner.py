"""源头雷达扫描编排."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from stock_news.common.storage import load_messages
from stock_news.models import ClassifiedMessage, RawMessage, Recommendation
from stock_news.source.features import (
    extract_terms,
    find_triggers,
    is_source_like,
    novelty_level,
    score_candidate,
    signal_priority,
    signal_type,
    stocks_from_recommendations,
    t3_verdict,
)
from stock_news.source.models import (
    Mention,
    MessageRow,
    SourceCandidate,
    SourceExtractItem,
    SourceScanResult,
)
from stock_news.source.storage import load_source_extracts


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


def load_corpus(data_dir: str, dates: list[date]) -> list[RawMessage]:
    """加载若干日期的全量群消息原文，作为历史/扩散统计的基准语料。

    只取 个人群（与 is_source_like 的来源约束一致），用于回答
    “这个词在本地历史上到底出现过没有、之后扩散到多少群多少人”。
    """
    corpus: list[RawMessage] = []
    for dt in dates:
        corpus.extend(load_messages(data_dir, dt, source="个人群"))
    return corpus


def _corpus_mentions(
    corpus: list[RawMessage],
    term: str,
    first_time: datetime,
) -> tuple[int, list[Mention]]:
    """在全量语料里按原文子串统计候选词的历史提及数与后续扩散。

    返回 (first_time 之前的提及次数, first_time 之后的扩散 Mention 列表)。
    扩散 Mention 不带个股信息（带股增强仍来自 source_extract 抽取层）。
    """
    previous = 0
    later: list[Mention] = []
    for msg in corpus:
        if term not in msg.raw_content:
            continue
        ts = msg.message_time
        if ts < first_time:
            previous += 1
        elif ts > first_time:
            row = MessageRow(
                date=ts.date(),
                message=msg,
                category=None,
                recommendations=(),
                terms=(term,),
                triggers=(),
            )
            later.append(Mention(term=term, row=row, stocks=()))
    return previous, later


def _surge_metrics(
    corpus: list[RawMessage],
    term: str,
    first_day: date,
    lookback_days: int,
) -> tuple[float, int, int]:
    """度量“低频拐点”：首现当日的放量相对前 lookback 天基线的突变。

    - baseline_daily: 首现日之前 lookback 天内的日均提及（不含首现当天）。
    - surge_count: 首现当天的提及次数。
    - surge_groups: 首现当天覆盖的不同群数。

    放量倍率由调用方用 surge_count / max(baseline_daily, 0.5) 计算。
    """
    baseline_start = first_day - timedelta(days=lookback_days)
    baseline_count = 0
    surge_count = 0
    surge_groups: set[str] = set()
    for msg in corpus:
        if term not in msg.raw_content:
            continue
        day = msg.message_time.date()
        if day == first_day:
            surge_count += 1
            if msg.group_name:
                surge_groups.add(msg.group_name)
        elif baseline_start <= day < first_day:
            baseline_count += 1
    baseline_daily = baseline_count / lookback_days if lookback_days > 0 else 0.0
    return round(baseline_daily, 2), surge_count, len(surge_groups)


def _t3_metrics(
    corpus: list[RawMessage],
    recommendations: dict[str, tuple[Recommendation, ...]],
    term: str,
    first_time: datetime,
    first_sender: str,
    horizon_days: int,
) -> tuple[int, int, tuple[str, ...]]:
    """T+3 事后回看：首现后 horizon 天内的真实扩散与个股落地。

    - t3_groups: 接力提及覆盖的独立群数。
    - t3_senders: 排除首现发布人后的独立接力人数（防单人刷屏虚高）。
    - t3_stocks: 这些接力消息里抽出的个股名（链路终点是个股埋伏）。
    """
    deadline = first_time + timedelta(days=horizon_days)
    groups: set[str] = set()
    senders: set[str] = set()
    stocks: set[str] = set()
    for msg in corpus:
        if term not in msg.raw_content:
            continue
        ts = msg.message_time
        if not (first_time < ts <= deadline):
            continue
        if msg.group_name:
            groups.add(msg.group_name)
        if msg.sender and msg.sender != first_sender:
            senders.add(msg.sender)
        for rec in recommendations.get(msg.message_id, ()):
            if rec.target_type != "stock":
                continue
            name = (rec.target_name or rec.ticker or "").strip()
            if name:
                stocks.add(name)
    return len(groups), len(senders), tuple(sorted(stocks)[:12])


def _fold_aliases(
    candidates: list[SourceCandidate],
) -> list[SourceCandidate]:
    """按首现 message_id 折叠同源候选：一条消息=一个信号。

    同一条首现消息切出的多个词，只保留扩散/放量最强的那个作主词，
    其余词作为 aliases 挂在主词下，避免一条消息在榜单里刷屏占位。
    """
    by_message: dict[str, list[SourceCandidate]] = defaultdict(list)
    order: list[str] = []
    for cand in candidates:
        mid = cand.first.row.message.message_id
        if mid not in by_message:
            order.append(mid)
        by_message[mid].append(cand)

    folded: list[SourceCandidate] = []
    for mid in order:
        group = by_message[mid]
        primary = min(
            group,
            key=lambda c: (c.signal_priority, -c.score),
        )
        aliases = tuple(c.term for c in group if c.term != primary.term)
        folded.append(replace(primary, aliases=aliases) if aliases else primary)
    return folded


def _source_triggers(item: SourceExtractItem) -> tuple[str, ...]:
    return {
        "new_concept": ("新概念",),
        "new_application": ("新应用",),
        "policy_catalyst": ("催化",),
        "industry_change": ("新方向",),
        "noise": (),
    }.get(item.source_type, ())


def build_source_extract_rows(
    data_dir: str,
    dates: list[date],
    recommendations: dict[str, tuple[Recommendation, ...]],
) -> tuple[list[MessageRow], bool]:
    rows: list[MessageRow] = []
    found_files = False
    root = Path(data_dir).expanduser()
    raw_by_id = {
        message.message_id: message
        for dt in dates
        for message in load_messages(data_dir, dt)
    }
    for dt in dates:
        path = root / dt.isoformat() / "source_extract" / "candidates.json"
        if not path.exists():
            continue
        found_files = True
        for item in load_source_extracts(data_dir, dt):
            if not item.is_source_candidate:
                continue
            message = raw_by_id.get(item.message_id) or RawMessage(
                source=item.source,
                sender=item.sender,
                message_time=item.message_time,
                raw_content=item.clean_title or item.evidence or "源头候选",
                group_name=item.group_name,
                fetch_time=item.message_time,
                fetch_window="source_extract",
            )
            rows.append(
                MessageRow(
                    date=item.message_time.date(),
                    message=message,
                    category="research",
                    recommendations=recommendations.get(item.message_id, ()),
                    terms=tuple(item.terms),
                    triggers=_source_triggers(item),
                )
            )
    return rows, found_files


def scan_source_candidates(
    data_dir: str,
    start: date,
    end: date,
    lookahead_days: int,
    top: int,
    max_message_chars: int,
    lookback_days: int = 30,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> SourceScanResult:
    observe_end = end + timedelta(days=lookahead_days)
    dates = available_dates(data_dir, observe_end)
    if not dates:
        raise ValueError("未找到本地数据目录")

    recommendations = load_recommendation_map(data_dir, dates)
    rows, found_source_extract = build_source_extract_rows(
        data_dir,
        dates,
        recommendations,
    )
    if not found_source_extract:
        raise ValueError("未找到 source_extract 产物，请先运行 sn source extract")

    # 历史/扩散基准语料：[start - lookback_days, observe_end] 的全量群消息原文。
    # 候选词的“历史提及/后续扩散”由此语料按原文子串匹配得到，
    # 而不再受限于只有少数几天的 source_extract 候选产物。
    corpus_start = start - timedelta(days=lookback_days)
    corpus_dates = [dt for dt in dates if corpus_start <= dt <= observe_end]
    corpus = load_corpus(data_dir, corpus_dates)

    candidate_by_term: dict[str, SourceCandidate] = {}
    for row in rows:
        if not is_source_like(row, start, end, max_message_chars):
            continue
        if window_start is not None and row.message.message_time < window_start:
            continue
        if window_end is not None and row.message.message_time > window_end:
            continue
        for term in row.terms:
            current_time = row.message.message_time
            previous_count, later = _corpus_mentions(corpus, term, current_time)
            baseline_daily, surge_count, surge_groups = _surge_metrics(
                corpus, term, current_time.date(), lookback_days
            )
            surge_ratio = round(surge_count / max(baseline_daily, 0.5), 1)
            t3_groups, t3_senders, t3_stocks = _t3_metrics(
                corpus,
                recommendations,
                term,
                current_time,
                row.message.sender,
                lookahead_days,
            )
            verified, verdict = t3_verdict(t3_groups, t3_senders, t3_stocks)
            # 后续扩散里带股信息仍取自 source_extract 抽取层（rows），
            # 与语料中的纯原文扩散合并去重不影响计数口径。
            stock_mentions: list[Mention] = []
            first = Mention(
                term=term,
                row=row,
                stocks=stocks_from_recommendations(row.recommendations),
            )
            score = score_candidate(
                first,
                previous_count,
                later,
                stock_mentions,
                baseline_daily=baseline_daily,
                surge_count=surge_count,
                surge_groups=surge_groups,
                surge_ratio=surge_ratio,
            )
            signal = signal_type(
                previous_count,
                later,
                stock_mentions,
                baseline_daily=baseline_daily,
                surge_ratio=surge_ratio,
                surge_groups=surge_groups,
            )
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
                novelty_level=novelty_level(previous_count, baseline_daily),
                previous_mentions=previous_count,
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
                baseline_daily=baseline_daily,
                surge_count=surge_count,
                surge_groups=surge_groups,
                surge_ratio=surge_ratio,
                t3_groups=t3_groups,
                t3_senders=t3_senders,
                t3_stocks=t3_stocks,
                verified=verified,
                verdict=verdict,
            )

    folded = _fold_aliases(list(candidate_by_term.values()))
    candidates = sorted(
        folded,
        key=lambda item: (
            not item.verified,
            item.signal_priority,
            -item.score,
            item.previous_mentions,
            item.first.row.message.message_time,
        ),
    )[:top]
    return SourceScanResult(
        start=start,
        end=end,
        window_start=window_start,
        window_end=window_end,
        lookahead_days=lookahead_days,
        scanned_messages=len(rows),
        candidate_count=len(folded),
        candidates=tuple(candidates),
    )
