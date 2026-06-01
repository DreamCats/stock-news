"""源头雷达特征、切词和规则打分."""

from __future__ import annotations

import re
from datetime import date

from stock_news.models import MessageCategory, Recommendation
from stock_news.source.models import Mention, MessageRow, SourceCandidate

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


def normalize_term(term: str) -> str:
    term = term.strip()
    term = re.sub(r"^[#【\[\(（\s]+|[】\]\)）\s]+$", "", term)
    term = re.sub(r"\s+", "", term)
    return term


def valid_term(term: str) -> bool:
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


def looks_like_theme(term: str) -> bool:
    if any(hint in term for hint in THEME_HINTS):
        return True
    if term.endswith(("协同", "产业链", "产业趋势")):
        return True
    return False


def extract_terms(text: str) -> tuple[str, ...]:
    terms: set[str] = set()

    for match in re.findall(r"#([^#\s，,。；;:：【】\[\]（）()<>《》]{2,24})", text):
        terms.add(normalize_term(match))

    for title in re.findall(r"【([^】]{2,40})】", text):
        for part in re.split(r"[：:|｜/&、，,\s]+", title):
            part = normalize_term(part)
            if looks_like_theme(part):
                terms.add(part)

    explicit_patterns = (
        r"([A-Za-z0-9\u4e00-\u9fff+·\-]{2,18})[，,、\s]*(?:AI|ai)?应用?(?<!最)新概念",
        r"([A-Za-z0-9\u4e00-\u9fff+·\-]{2,18})[，,、\s]*(?<!最)(?:新方向|新题材|新应用|新场景)",
        r"([A-Za-z0-9\u4e00-\u9fff+·\-]{2,18})(?:进入新阶段|从概念到落地|概念到落地)",
    )
    for pattern in explicit_patterns:
        for match in re.findall(pattern, text):
            terms.add(normalize_term(match))

    suffixes = ("协同", "新应用", "新场景", "产业链", "产业趋势", "商业化")
    suffix_pattern = "|".join(suffixes)
    for match in re.findall(
        rf"([A-Za-z0-9\u4e00-\u9fff+·\-]{{2,14}}(?:{suffix_pattern}))",
        text,
    ):
        terms.add(normalize_term(match))

    plus_pattern = (
        r"([A-Za-z0-9\u4e00-\u9fff]{1,8}"
        r"\+[A-Za-z0-9\u4e00-\u9fff]{1,8})"
    )
    for match in re.findall(plus_pattern, text):
        term = normalize_term(match)
        if looks_like_theme(term):
            terms.add(term)

    return tuple(sorted(term for term in terms if valid_term(term)))


def find_triggers(text: str) -> tuple[str, ...]:
    triggers: list[str] = []
    for term in TRIGGER_TERMS:
        for match in re.finditer(re.escape(term), text):
            if match.start() > 0 and text[match.start() - 1] == "最":
                continue
            triggers.append(term)
            break
    return tuple(triggers)


def stocks_from_recommendations(
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


def snippet(text: str, limit: int = 80) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def is_source_like(row: MessageRow, start: date, end: date, max_chars: int) -> bool:
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


def score_candidate(
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


def novelty_level(previous_count: int) -> str:
    if previous_count == 0:
        return "全新"
    if previous_count <= 2:
        return "低频"
    if previous_count <= 20:
        return "已有"
    return "高频旧主题"


def signal_type(
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


def signal_priority(signal: str) -> int:
    priorities = {
        "新词源头": 0,
        "低频新线索": 1,
        "扩散带股": 2,
        "旧主题再催化": 3,
        "普通线索": 4,
    }
    return priorities.get(signal, 9)


def evidence(candidate: SourceCandidate) -> list[str]:
    out: list[str] = []
    if candidate.previous_mentions == 0:
        out.append("本地历史首次出现")
    elif candidate.previous_mentions <= 2:
        out.append(f"历史低频，仅 {candidate.previous_mentions} 次")
    else:
        out.append(f"历史已有 {candidate.previous_mentions} 次")
    if candidate.later_mentions:
        out.append(
            "后续扩散 "
            f"{candidate.later_mentions} 次/{candidate.later_days} 天/"
            f"{candidate.later_groups} 群/{candidate.later_senders} 人"
        )
    if candidate.first_stock is not None:
        out.append("后续出现带股消息")
    return out
