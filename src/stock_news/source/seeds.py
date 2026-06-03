"""新源头雷达：as-of 源头种子扫描."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from stock_news.common.storage import load_messages
from stock_news.models import (
    ClassifiedMessage,
    MessageCategory,
    RawMessage,
    Recommendation,
)
from stock_news.source.models import (
    Mention,
    MessageRow,
    SourceSeedCandidate,
    SourceSeedResult,
)
from stock_news.source.storage import load_source_structures, structures_path
from stock_news.source.utils import (
    available_dates,
    load_classified_map,
    load_recommendation_map,
    parse_date,
    stocks_from_recommendations,
)

SOURCE_CUES = (
    "新概念",
    "新方向",
    "新题材",
    "新应用",
    "新场景",
    "产业趋势",
    "预期差",
    "从0到1",
    "0到1",
    "拐点",
    "映射",
    "代名词",
)

NOISE_SUBSTRINGS = (
    "腾讯会议",
    "会议号",
    "密码",
    "报名",
    "联系人",
    "日报",
    "周报",
    "月报",
)

COMMON_HUA_SUFFIXES = (
    "强化",
    "深化",
    "催化",
    "变化",
    "优化",
    "转化",
    "规模化",
    "分化",
    "量化",
    "年化",
    "孵化",
    "美化",
    "绿化",
)

MODIFIER_NOISE_PREFIXES = (
    "对",
    "把",
    "将",
    "采用",
    "可以",
    "加速",
    "推动",
    "带动",
)

ABSTRACT_ANCHORS = {
    "共振",
    "拐点",
    "时代",
    "趋势",
    "机会",
    "价值",
    "弹性",
    "逻辑",
    "瓶颈",
    "平台",
    "空间",
}

LEADING_MODIFIER_WORDS = (
    "正在",
    "加速",
    "开始",
    "持续",
    "有望",
    "进入",
    "全面",
)

MIN_STRUCTURE_CONFIDENCE = 0.65


@dataclass(frozen=True)
class _SpanCandidate:
    anchor: str
    modifier: str
    novel: str
    relation_type: str


@dataclass(frozen=True)
class _CorpusItem:
    message: RawMessage
    text: str
    upper_text: str


def parse_as_of(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    normalized = value.strip()
    if normalized in {"now", "today"}:
        return datetime.now().replace(microsecond=0)
    if normalized == "yesterday":
        return datetime.combine(date.today() - timedelta(days=1), time.max).replace(
            microsecond=0
        )
    if "T" not in normalized and " " not in normalized and len(normalized) == 10:
        return datetime.combine(parse_date(normalized), time.max).replace(microsecond=0)
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", normalized):
        parts = [int(part) for part in normalized.split(":")]
        hour, minute = parts[0], parts[1]
        second = parts[2] if len(parts) == 3 else 0
        return datetime.combine(fallback.date(), time(hour, minute, second))
    return datetime.fromisoformat(normalized.replace(" ", "T"))


def _normalize_span(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^[#【\[\(（\s]+|[】\]\)）\s]+$", "", value)
    return re.sub(r"\s+", "", value)


def _valid_modifier(value: str) -> bool:
    if not (2 <= len(value) <= 10):
        return False
    if re.fullmatch(r"\d+|[A-Za-z]{1,2}", value):
        return False
    if value.endswith(COMMON_HUA_SUFFIXES):
        return False
    if value.startswith(MODIFIER_NOISE_PREFIXES):
        return False
    if "和" in value or "与" in value:
        return False
    return not any(part in value for part in NOISE_SUBSTRINGS)


def _valid_anchor(value: str) -> bool:
    if not (2 <= len(value) <= 12):
        return False
    if re.fullmatch(r"\d+", value):
        return False
    if value in ABSTRACT_ANCHORS:
        return False
    return not any(part in value for part in NOISE_SUBSTRINGS)


def _canonical_modifier(value: str) -> str:
    value = _normalize_span(value)
    changed = True
    while changed:
        changed = False
        for word in LEADING_MODIFIER_WORDS:
            if value.startswith(word) and len(value) > len(word) + 1:
                value = value[len(word) :]
                changed = True
        if value.endswith("的") and len(value) > 2:
            value = value[:-1]
            changed = True
    return value


def _canonical_span(span: _SpanCandidate) -> _SpanCandidate | None:
    anchor = _normalize_span(span.anchor)
    modifier = _canonical_modifier(span.modifier)
    novel = _normalize_span(span.novel)
    relation_type = span.relation_type
    if modifier.endswith("化") and anchor:
        relation_type = "A化B"
        novel = f"{modifier}的{anchor}"
    elif span.relation_type == "A化B":
        relation_type = "modifier-anchor"
    if not _valid_anchor(anchor) or not _valid_modifier(modifier) or len(novel) < 4:
        return None
    return _SpanCandidate(
        anchor=anchor,
        modifier=modifier,
        novel=novel,
        relation_type=relation_type,
    )


def _add_candidate(
    out: dict[tuple[str, str, str], _SpanCandidate],
    anchor: str,
    modifier: str,
    novel: str,
    relation_type: str,
) -> None:
    anchor = _normalize_span(anchor)
    modifier = _canonical_modifier(modifier)
    novel = _normalize_span(novel)
    if relation_type == "A化B":
        novel = f"{modifier}的{anchor}"
    if not _valid_anchor(anchor) or not _valid_modifier(modifier) or len(novel) < 4:
        return
    if anchor == modifier:
        return
    key = (anchor.upper() if anchor.isascii() else anchor, modifier, relation_type)
    current = out.get(key)
    candidate = _SpanCandidate(
        anchor=anchor,
        modifier=modifier,
        novel=novel,
        relation_type=relation_type,
    )
    if current is None or len(candidate.novel) > len(current.novel):
        out[key] = candidate


def extract_span_candidates(text: str) -> tuple[_SpanCandidate, ...]:
    """从一条消息里拆出“成熟锚点 + 陌生修饰”的组合候选.

    这是 V0 的本地解析器。后续 LLM 结构抽取接入后，应产出同一套字段。
    """
    out: dict[tuple[str, str, str], _SpanCandidate] = {}
    compact = _normalize_span(text)

    for match in re.finditer(
        r"([A-Za-z0-9\u4e00-\u9fff]{2,12})化的([A-Za-z0-9\u4e00-\u9fff]{2,12})"
        r"|([A-Za-z0-9\u4e00-\u9fff]{2,12})化([A-Z][A-Z0-9]{1,10})",
        compact,
    ):
        root = match.group(1) or match.group(3)
        anchor = match.group(2) or match.group(4)
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,10}", anchor):
            continue
        modifier = f"{root}化"
        _add_candidate(out, anchor, modifier, match.group(0), "A化B")

    for match in re.finditer(
        r"(?<![A-Za-z0-9])([A-Za-z0-9]{2,12})[-/]([A-Z][A-Z0-9]{1,10})(?![A-Za-z0-9])",
        compact,
    ):
        modifier, anchor = match.groups()
        _add_candidate(out, anchor, modifier, match.group(0), "prefix-anchor")

    return tuple(out.values())


def _structure_span_candidates(
    data_dir: str,
    dates: list[date],
    required_dates: list[date],
) -> dict[str, tuple[_SpanCandidate, ...]]:
    missing = [
        dt
        for dt in required_dates
        if not structures_path(data_dir, dt, create=False).exists()
    ]
    if missing:
        missing_text = "、".join(dt.isoformat() for dt in missing)
        first = missing[0].isoformat()
        raise ValueError(
            f"{missing_text} source_extract 为空或缺少 structures.json，"
            f"请先运行: sn source extract --date {first}"
        )

    grouped: dict[str, list[_SpanCandidate]] = {}
    for dt in dates:
        for item in load_source_structures(data_dir, dt):
            if not item.is_candidate:
                continue
            if item.confidence < MIN_STRUCTURE_CONFIDENCE:
                continue
            if not item.anchor_span or not item.modifier_span or not item.novel_span:
                continue
            candidate = _SpanCandidate(
                anchor=item.anchor_span,
                modifier=item.modifier_span,
                novel=item.novel_span,
                relation_type=item.relation_type,
            )
            canonical = _canonical_span(candidate)
            if canonical is None:
                continue
            grouped.setdefault(item.message_id, []).append(canonical)
    return {message_id: tuple(items) for message_id, items in grouped.items()}


def _build_corpus_items(messages: list[RawMessage]) -> list[_CorpusItem]:
    return [
        _CorpusItem(
            message=msg,
            text=_normalize_span(msg.raw_content),
            upper_text=_normalize_span(msg.raw_content).upper(),
        )
        for msg in messages
    ]


def _load_messages_until(
    data_dir: str, dates: list[date], as_of_time: datetime
) -> list[RawMessage]:
    messages: list[RawMessage] = []
    for dt in dates:
        for msg in load_messages(data_dir, dt):
            if msg.message_time <= as_of_time:
                messages.append(msg)
    return sorted(messages, key=lambda msg: msg.message_time)


def _row_for_message(
    message: RawMessage,
    classified: dict[str, ClassifiedMessage],
    recommendations: dict[str, tuple[Recommendation, ...]],
) -> MessageRow:
    classified_msg = classified.get(message.message_id)
    category = classified_msg.category.value if classified_msg else None
    return MessageRow(
        date=message.message_time.date(),
        message=message,
        category=category,
        recommendations=recommendations.get(message.message_id, ()),
        terms=(),
        triggers=(),
    )


def _looks_candidate_message(
    msg: RawMessage,
    row: MessageRow,
    max_message_chars: int,
) -> bool:
    if msg.source not in {"个人群", "个人消息"}:
        return False
    if len(msg.raw_content) > max_message_chars:
        return False
    if any(part in msg.raw_content for part in NOISE_SUBSTRINGS):
        return False
    if row.category not in {
        MessageCategory.RECOMMENDATION.value,
        MessageCategory.RESEARCH.value,
        MessageCategory.EVENT.value,
        MessageCategory.NOISE.value,
        None,
    }:
        return False
    compact = _normalize_span(msg.raw_content)
    has_combo_shape = bool(
        re.search(
            r"[A-Za-z0-9\u4e00-\u9fff]{2,12}化的[A-Za-z0-9\u4e00-\u9fff]{2,12}"
            r"|[A-Za-z0-9\u4e00-\u9fff]{2,12}化[A-Z][A-Z0-9]{1,10}",
            compact,
        )
        or re.search(
            r"(?<![A-Za-z0-9])[A-Za-z0-9]{2,12}[-/][A-Z][A-Z0-9]{1,10}(?![A-Za-z0-9])",
            compact,
        )
    )
    return has_combo_shape or any(cue in msg.raw_content for cue in SOURCE_CUES)


def _contains_combo_text(text: str, upper_text: str, span: _SpanCandidate) -> bool:
    return (
        span.novel in text
        or span.novel.upper() in upper_text
        or (
            (span.anchor in text or span.anchor.upper() in upper_text)
            and (span.modifier in text or span.modifier.upper() in upper_text)
        )
    )


def _count_prior(
    corpus: list[_CorpusItem],
    span: _SpanCandidate,
    first_time: datetime,
) -> tuple[int, int, int, int]:
    anchor = modifier = exact = combo = 0
    for item in corpus:
        if item.message.message_time >= first_time:
            continue
        anchor_hit = span.anchor in item.text or span.anchor.upper() in item.upper_text
        modifier_hit = (
            span.modifier in item.text or span.modifier.upper() in item.upper_text
        )
        exact_hit = span.novel in item.text or span.novel.upper() in item.upper_text
        if anchor_hit:
            anchor += 1
        if modifier_hit:
            modifier += 1
        if exact_hit:
            exact += 1
        if exact_hit or (anchor_hit and modifier_hit):
            combo += 1
    return anchor, modifier, exact, combo


def _mentions_between(
    corpus: list[_CorpusItem],
    span: _SpanCandidate,
    start_time: datetime,
    end_time: datetime,
) -> list[RawMessage]:
    out: list[RawMessage] = []
    for item in corpus:
        if start_time <= item.message.message_time <= end_time and _contains_combo_text(
            item.text, item.upper_text, span
        ):
            out.append(item.message)
    return out


def _mapped_stocks(
    messages: list[RawMessage],
    recommendations: dict[str, tuple[Recommendation, ...]],
) -> tuple[str, ...]:
    stocks: list[str] = []
    for msg in messages:
        for stock in stocks_from_recommendations(
            recommendations.get(msg.message_id, ())
        ):
            if stock not in stocks:
                stocks.append(stock)
    return tuple(stocks[:12])


def _status(
    prior_combo: int,
    asof_groups: int,
    followup_senders: int,
    followup_groups: int,
    mapped_stocks: tuple[str, ...],
) -> str:
    if prior_combo > 8:
        return "old_theme"
    if mapped_stocks:
        return "mapped"
    if followup_groups >= 3 or followup_senders >= 2:
        return "spreading_watch"
    return "source_seed"


def _status_priority(status: str) -> int:
    return {
        "source_seed": 0,
        "spreading_watch": 1,
        "mapped": 0,
        "old_theme": 4,
    }.get(status, 9)


def _relation_priority(relation_type: str) -> int:
    return {
        "A化B": 0,
        "prefix-anchor": 1,
        "modifier-anchor": 2,
        "anchor-extension": 3,
    }.get(relation_type, 9)


def _score(
    prior_exact: int,
    prior_combo: int,
    prior_anchor: int,
    asof_mentions: int,
    asof_groups: int,
    followup_senders: int,
    followup_groups: int,
    mapped_stocks: tuple[str, ...],
    source_quality: float,
) -> tuple[float, float, float, float, float]:
    novelty = 1.0
    if prior_exact:
        novelty -= min(prior_exact, 10) * 0.05
    if prior_combo:
        novelty -= min(prior_combo, 10) * 0.08
    if prior_anchor == 0:
        novelty -= 0.15
    novelty = max(0.0, round(novelty, 2))

    earliness = 1.0
    if asof_groups >= 5:
        earliness = 0.35
    elif asof_groups >= 3:
        earliness = 0.55
    elif asof_mentions >= 3:
        earliness = 0.75
    earliness = round(earliness, 2)

    askability = round((novelty * 0.45) + (earliness * 0.35) + source_quality * 0.2, 2)
    trade = min(1.0, followup_senders * 0.18 + followup_groups * 0.12)
    if mapped_stocks:
        trade = max(trade, 0.8)
    trade = round(trade, 2)

    total = round(askability * 60 + trade * 25 + min(asof_groups, 5) * 3, 1)
    return total, novelty, earliness, askability, trade


def _source_quality(row: MessageRow) -> float:
    score = 0.55
    if row.category == MessageCategory.RESEARCH.value:
        score += 0.2
    if row.category == MessageCategory.EVENT.value:
        score += 0.1
    if any(cue in row.message.raw_content for cue in SOURCE_CUES):
        score += 0.15
    if len(row.message.raw_content) <= 500:
        score += 0.1
    return min(score, 1.0)


def _evidence(
    span: _SpanCandidate,
    prior_anchor: int,
    prior_modifier: int,
    prior_exact: int,
    prior_combo: int,
    asof_mentions: int,
    asof_groups: int,
    followup_senders: int,
    followup_groups: int,
    mapped_stocks: tuple[str, ...],
) -> tuple[str, ...]:
    out = [
        f"锚点 {span.anchor} 历史 {prior_anchor} 次",
        f"修饰词 {span.modifier} 历史 {prior_modifier} 次",
        f"精确组合历史 {prior_exact} 次",
        f"同锚点+修饰组合历史 {prior_combo} 次",
        f"截至 as_of 已出现 {asof_mentions} 次/{asof_groups} 群",
    ]
    if followup_senders or followup_groups:
        out.append(f"首现后接力 {followup_senders} 人/{followup_groups} 群")
    if mapped_stocks:
        out.append("已映射个股：" + "、".join(mapped_stocks[:6]))
    return tuple(out)


def scan_source_seeds(
    data_dir: str,
    start: date,
    end: date,
    as_of_time: datetime,
    lookback_days: int,
    top: int,
    max_message_chars: int,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> SourceSeedResult:
    del top
    observe_end = min(end, as_of_time.date())
    all_dates = available_dates(data_dir, observe_end)
    if not all_dates:
        raise ValueError("未找到本地数据目录")

    corpus_start = start - timedelta(days=lookback_days)
    dates = [dt for dt in all_dates if corpus_start <= dt <= observe_end]
    classified = load_classified_map(data_dir, dates)
    recommendations = load_recommendation_map(data_dir, dates)
    required_structure_dates = [
        dt for dt in dates if start <= dt <= end and dt <= as_of_time.date()
    ]
    structure_spans = _structure_span_candidates(
        data_dir,
        dates,
        required_structure_dates,
    )
    raw_corpus = _load_messages_until(data_dir, dates, as_of_time)
    corpus = _build_corpus_items(raw_corpus)

    candidates_by_signal: dict[str, SourceSeedCandidate] = {}
    scanned = 0
    for msg in raw_corpus:
        if not (start <= msg.message_time.date() <= end):
            continue
        if window_start is not None and msg.message_time < window_start:
            continue
        if window_end is not None and msg.message_time > window_end:
            continue
        row = _row_for_message(msg, classified, recommendations)
        if row.category == MessageCategory.RECOMMENDATION.value:
            continue
        spans = structure_spans.get(msg.message_id, ())
        if not spans:
            continue
        scanned += 1
        for span in spans:
            prior_anchor, prior_modifier, prior_exact, prior_combo = _count_prior(
                corpus, span, msg.message_time
            )
            if prior_anchor == 0:
                continue
            mentions = _mentions_between(corpus, span, msg.message_time, as_of_time)
            followups = [item for item in mentions if item.message_id != msg.message_id]
            asof_groups = len({item.group_name for item in mentions if item.group_name})
            asof_senders = len({item.sender for item in mentions if item.sender})
            followup_groups = len(
                {item.group_name for item in followups if item.group_name}
            )
            followup_senders = len({item.sender for item in followups if item.sender})
            stocks = _mapped_stocks(mentions, recommendations)
            quality = _source_quality(row)
            score, novelty, earliness, askability, trade = _score(
                prior_exact,
                prior_combo,
                prior_anchor,
                len(mentions),
                asof_groups,
                followup_senders,
                followup_groups,
                stocks,
                quality,
            )
            status = _status(
                prior_combo,
                asof_groups,
                followup_senders,
                followup_groups,
                stocks,
            )
            signal_id = f"{span.anchor}::{span.relation_type}::{span.modifier}"
            first = Mention(term=span.novel, row=row, stocks=())
            candidate = SourceSeedCandidate(
                signal_id=signal_id,
                status=status,
                anchor_span=span.anchor,
                modifier_span=span.modifier,
                novel_span=span.novel,
                relation_type=span.relation_type,
                score=score,
                novelty_strength=novelty,
                earliness_score=earliness,
                askability_score=askability,
                trade_potential_score=trade,
                first=first,
                prior_anchor_mentions=prior_anchor,
                prior_modifier_mentions=prior_modifier,
                prior_exact_mentions=prior_exact,
                prior_combo_mentions=prior_combo,
                asof_mentions=len(mentions),
                asof_groups=asof_groups,
                asof_senders=asof_senders,
                followup_groups=followup_groups,
                followup_senders=followup_senders,
                mapped_stocks=stocks,
                evidence=_evidence(
                    span,
                    prior_anchor,
                    prior_modifier,
                    prior_exact,
                    prior_combo,
                    len(mentions),
                    asof_groups,
                    followup_senders,
                    followup_groups,
                    stocks,
                ),
            )
            existing = candidates_by_signal.get(signal_id)
            if existing is None or (
                candidate.first.row.message.message_time
                < existing.first.row.message.message_time
            ):
                candidates_by_signal[signal_id] = candidate

    candidates = tuple(
        sorted(
            candidates_by_signal.values(),
            key=lambda item: (
                _status_priority(item.status),
                -item.score,
                -item.askability_score,
                _relation_priority(item.relation_type),
                -item.novelty_strength,
                -item.trade_potential_score,
                item.first.row.message.message_time,
            ),
        )
    )
    return SourceSeedResult(
        start=start,
        end=end,
        as_of_time=as_of_time,
        window_start=window_start,
        window_end=window_end,
        lookback_days=lookback_days,
        scanned_messages=scanned,
        candidate_count=len(candidates_by_signal),
        candidates=candidates,
        total_candidate_count=len(candidates_by_signal),
    )
