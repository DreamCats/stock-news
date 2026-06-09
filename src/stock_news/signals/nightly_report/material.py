"""每日晚报本地材料提炼."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from stock_news.commands.strategy.utils import _rec_time, _target_name
from stock_news.models import Recommendation

_DIMENSION_KEYWORDS = {
    "valuation": ("目标市值", "空间", "PE", "估值", "倍", "亿"),
    "position": ("龙头", "唯一", "份额", "卡位", "供应商", "国产替代", "核心"),
    "catalyst": ("订单", "客户", "涨价", "提价", "交付", "突破", "绑定", "招标"),
    "capacity": ("产能", "扩产", "满负荷", "良率", "毛利", "净利", "业绩", "利润"),
}
_NOISE_WORDS = {
    "重点推荐",
    "重点关注",
    "继续推荐",
    "建议关注",
    "强烈推荐",
    "投资建议",
    "持续坚定推荐",
    "核心推荐",
    "继续坚定推荐",
    "放心买入",
    "送钱机会",
}
_TAG_WORDS = (
    "红包",
    "礼物",
    "玫瑰",
    "太阳",
    "烟花",
    "福",
    "庆祝",
    "强",
    "重点",
)


def build_nightly_items(
    payload: dict[str, Any],
    recommendations: list[Recommendation],
) -> list[dict[str, Any]]:
    recs_by_target = _group_recommendations_by_target(recommendations)
    target_names = {
        str(candidate.get("target_name") or "")
        for candidate in payload.get("candidate_trades") or []
        if candidate.get("target_name")
    }
    items = []
    for index, candidate in enumerate(payload.get("candidate_trades") or [], start=1):
        senders = [str(sender) for sender in candidate.get("senders", []) if sender]
        target_name = str(candidate.get("target_name") or "")
        target_recs = recs_by_target.get(target_name, [])
        source_fragments = _source_fragments(target_name, target_recs, target_names)
        risks = _risk_fragments(target_recs)
        brief = _template_boss_line(candidate, source_fragments, risks)
        items.append(
            {
                "rank": index,
                "target_name": target_name,
                "ticker": candidate.get("ticker"),
                "score": candidate.get("score"),
                "recommendation_count": len(target_recs),
                "senders": senders,
                "senders_text": "、".join(senders[:5]) or "-",
                "why_selected": candidate.get("why_selected") or [],
                "source_fragments": source_fragments,
                "risks": risks,
                "logic_source": "template",
                "brief": brief,
            }
        )
    return items


def clean_boss_line(text: str, max_len: int) -> str:
    line = _clean_fragment(text)
    line = line.replace("...", "，").replace("…", "，")
    line = re.sub(r"\s+", " ", line).strip(" ，,；;")
    return _clip_text(line, max_len=max_len)


def is_valid_boss_line(
    target_name: str,
    line: str,
    target_names: set[str],
) -> bool:
    if len(line) < 18 or len(line) > 150:
        return False
    if "..." in line or "…" in line:
        return False
    if _contains_contact_noise(line):
        return False
    if _other_target_count(target_name, line, target_names) > 0:
        return False
    return True


def _group_recommendations_by_target(
    recommendations: list[Recommendation],
) -> dict[str, list[Recommendation]]:
    grouped: dict[str, list[Recommendation]] = {}
    for rec in recommendations:
        grouped.setdefault(_target_name(rec), []).append(rec)
    for recs in grouped.values():
        recs.sort(key=lambda rec: _rec_time(rec, datetime.min), reverse=True)
    return grouped


def _source_fragments(
    target_name: str,
    recs: list[Recommendation],
    target_names: set[str],
) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for rec in recs:
        for source_rank, text in enumerate(
            [rec.reasoning, rec.evidence, rec.raw_content],
            start=1,
        ):
            if not text:
                continue
            for sentence in _split_material(str(text)):
                if _is_raw_noise(sentence):
                    continue
                fragment = _clean_fragment(sentence)
                fragment = _normalize_target_fragment(target_name, fragment)
                if not _is_useful_fragment(target_name, fragment, target_names):
                    continue
                raw_score = _fragment_score(target_name, fragment)
                if source_rank == 3:
                    if target_name and target_name not in fragment:
                        continue
                    if raw_score < 3:
                        continue
                candidates.append((raw_score - source_rank, fragment))

    out: list[str] = []
    seen: set[str] = set()
    for _, fragment in sorted(candidates, key=lambda item: item[0], reverse=True):
        normalized = fragment.casefold()
        if normalized in seen:
            continue
        if any(fragment in existing or existing in fragment for existing in out):
            continue
        seen.add(normalized)
        out.append(_clip_text(fragment, max_len=105))
        if len(out) >= 5:
            break
    return out


def _risk_fragments(recs: list[Recommendation]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for rec in recs:
        risk = _clean_fragment(rec.risk_note or "")
        if not risk or risk in seen:
            continue
        seen.add(risk)
        out.append(_clip_text(risk, max_len=70))
        if len(out) >= 2:
            break
    return out


def _template_boss_line(
    candidate: dict[str, Any],
    fragments: list[str],
    risks: list[str],
) -> str:
    if fragments:
        selected = _select_boss_fragments(fragments)
        line = "，".join(selected)
        if risks:
            line = f"{line}；待验证{risks[0]}"
        return clean_boss_line(line, max_len=135)

    clues = candidate.get("evidences") or candidate.get("reasons") or []
    clue = "，".join(
        _clip_text(_clean_fragment(str(item)), max_len=55) for item in clues[:3] if item
    )
    if clue:
        return clean_boss_line(clue, max_len=135)
    return "本窗口有新增推荐，但结构化证据不足，需要回看原文验证产业逻辑。"


def _select_boss_fragments(fragments: list[str]) -> list[str]:
    selected: list[str] = []

    for dimension in ("valuation", "position", "catalyst", "capacity"):
        for fragment in fragments:
            if fragment in selected:
                continue
            if _fragment_dimension(fragment) == dimension:
                selected.append(fragment)
                break

    for fragment in fragments:
        if len(selected) >= 3:
            break
        if fragment not in selected:
            selected.append(fragment)

    if not selected and fragments:
        selected.append(fragments[0])
    return selected[:3]


def _fragment_dimension(fragment: str) -> str:
    for dimension, keywords in _DIMENSION_KEYWORDS.items():
        if any(keyword in fragment for keyword in keywords):
            return dimension
    return "other"


def _split_material(text: str) -> list[str]:
    compact = re.sub(r"[ \t]+", " ", text.replace("\r", "\n"))
    parts = re.split(r"[\n。！？!?；;]+", compact)
    return [part.strip(" -—:：,，[]【】（）()") for part in parts if part.strip()]


def _clean_fragment(text: str) -> str:
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"[0-9][\ufe0f]?\u20e3", "", text)
    text = re.sub(r"1[3-9]\d{9}", "", text)
    text = re.sub(r"\b\d{3,4}[- ]?\d{7,8}\b", "", text)
    for tag in _TAG_WORDS:
        text = text.replace(f"[{tag}]", "")
        text = text.replace(f"【{tag}】", "")
        text = text.replace(f"{tag}]", "")
    for word in _NOISE_WORDS:
        text = text.replace(word, "")
    text = re.sub(r"^[A-Za-z0-9]{2,12}】", "", text)
    text = re.sub(r"【[A-Za-z][^】]{0,24}$", "", text)
    text = re.sub(r"\b[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}$", "", text)
    text = re.sub(r"东北通信】|东吴电子】|长江电子/建材】", "", text)
    text = re.sub(r"材料[0-9一二三四五六七八九十]+[-—]", "", text)
    text = re.sub(r"^#+", "", text)
    text = text.replace("#", "")
    text = re.sub(r"^[0-9一二三四五六七八九十]+[、.．)]", "", text)
    text = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]+", "", text)
    text = text.replace("...", "，").replace("…", "，")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -—:：,，[]【】（）()")


def _normalize_target_fragment(target_name: str, fragment: str) -> str:
    if target_name:
        fragment = re.sub(
            rf"^[【\[]?{re.escape(target_name)}[】\]]?[：:，, ]*",
            "",
            fragment,
        )
        fragment = re.sub(
            rf"^[^，,：:；;]{{0,36}}[【\[]?{re.escape(target_name)}[】\]]?[：:]",
            "",
            fragment,
        )
    return fragment.strip(" -—:：,，[]【】（）()")


def _is_raw_noise(text: str) -> bool:
    noise_patterns = [
        r"一篮子标的",
        r"其他.{0,8}标的",
        r"弹性角度",
        r"线上交流",
        r"会议",
        r"电话会",
        r"联系人",
        r"郭威秀",
        r"Rogelio",
        r"强call",
        r"强推",
        r"放心买入",
        r"送钱机会",
        r"蠢蠢欲动",
        r"重点更新",
        r"核心推荐的",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in noise_patterns)


def _is_useful_fragment(
    target_name: str,
    fragment: str,
    target_names: set[str],
) -> bool:
    if len(fragment) < 6 or len(fragment) > 160:
        return False
    if fragment == target_name:
        return False
    if fragment in _NOISE_WORDS:
        return False
    if _contains_contact_noise(fragment):
        return False
    if _other_target_count(target_name, fragment, target_names) > 0:
        return False
    return True


def _fragment_score(target_name: str, fragment: str) -> int:
    score = 0
    if target_name and target_name in fragment:
        score += 4
    if re.search(r"\d|[一二三四五六七八九十百千万亿]+[倍年月日]", fragment):
        score += 8
    keywords = [
        "目标市值",
        "空间",
        "订单",
        "客户",
        "供应链",
        "涨价",
        "提价",
        "份额",
        "产能",
        "毛利",
        "净利",
        "业绩",
        "交付",
        "突破",
        "绑定",
        "独家",
        "龙头",
        "卡位",
        "安全边际",
    ]
    score += sum(3 for keyword in keywords if keyword in fragment)
    if 18 <= len(fragment) <= 90:
        score += 2
    return score


def _contains_contact_noise(text: str) -> bool:
    return bool(re.search(r"1[3-9]\d{9}|\b\d{3,4}[- ]?\d{7,8}\b", text))


def _other_target_count(
    target_name: str,
    text: str,
    target_names: set[str],
) -> int:
    return sum(
        1
        for name in target_names
        if name and name != target_name and len(name) >= 2 and name in text
    )


def _clip_text(text: str, max_len: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip(" ，,；;")
    if len(compact) <= max_len:
        return compact
    clipped = compact[:max_len].rstrip(" ，,；;")
    if "，" in clipped:
        clipped = clipped.rsplit("，", 1)[0]
    return clipped.rstrip(" ，,；;") or compact[:max_len].rstrip(" ，,；;")
