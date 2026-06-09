"""源头雷达结果展示与 Markdown 渲染."""

from __future__ import annotations

from collections.abc import Callable

from stock_news.source.models import SourceSeedCandidate, SourceSeedResult
from stock_news.source.utils import snippet

ACTIONABLE_STATUSES = {"source_seed", "spreading_watch", "mapped"}

STATUS_LABELS = {
    "source_seed": "源头种子",
    "spreading_watch": "扩散验证",
    "mapped": "个股映射",
    "old_theme": "历史老主题",
}

STATUS_ORDER = ("source_seed", "spreading_watch", "mapped", "old_theme")

BRIEF_MARKDOWN_LIMIT = 3


def seed_to_dict(candidate: SourceSeedCandidate) -> dict[str, object]:
    first = candidate.first
    return {
        "signal_id": candidate.signal_id,
        "status": candidate.status,
        "anchor_span": candidate.anchor_span,
        "modifier_span": candidate.modifier_span,
        "novel_span": candidate.novel_span,
        "relation_type": candidate.relation_type,
        "score": candidate.score,
        "novelty_strength": candidate.novelty_strength,
        "earliness_score": candidate.earliness_score,
        "askability_score": candidate.askability_score,
        "trade_potential_score": candidate.trade_potential_score,
        "history": {
            "prior_anchor_mentions": candidate.prior_anchor_mentions,
            "prior_modifier_mentions": candidate.prior_modifier_mentions,
            "prior_exact_mentions": candidate.prior_exact_mentions,
            "prior_combo_mentions": candidate.prior_combo_mentions,
        },
        "as_of": {
            "mentions": candidate.asof_mentions,
            "groups": candidate.asof_groups,
            "senders": candidate.asof_senders,
        },
        "followup": {
            "groups": candidate.followup_groups,
            "senders": candidate.followup_senders,
            "mapped_stocks": list(candidate.mapped_stocks),
        },
        "first": {
            "time": first.row.message.message_time.isoformat(),
            "source": first.row.message.source,
            "group": first.row.message.group_name,
            "sender": first.row.message.sender,
            "message_id": first.row.message.message_id,
            "category": first.row.category,
            "snippet": snippet(first.row.message.raw_content),
        },
        "evidence": list(candidate.evidence),
    }


def seed_window_label(result: SourceSeedResult) -> str:
    if result.window_start is not None and result.window_end is not None:
        start = result.window_start.strftime("%Y-%m-%d %H:%M:%S")
        end = result.window_end.strftime("%Y-%m-%d %H:%M:%S")
        return f"{start} 到 {end}"
    return f"{result.start} 到 {result.end}"


def bucket_candidates(
    candidates: tuple[SourceSeedCandidate, ...],
) -> dict[str, tuple[SourceSeedCandidate, ...]]:
    return {
        status: tuple(item for item in candidates if item.status == status)
        for status in STATUS_ORDER
    }


def format_seed_plain(result: SourceSeedResult) -> str:
    label = seed_window_label(result)
    if not result.candidates:
        hidden = result.hidden_count
        suffix = (
            f"（已隐藏 {hidden} 个 old_theme，可加 --include-closed 查看）"
            if hidden
            else ""
        )
        return f"{label} 未发现可行动源头候选{suffix}\n"

    lines = [
        f"{label} 源头雷达候选 {len(result.candidates)} 个 "
        f"(as_of={result.as_of_time.strftime('%Y-%m-%d %H:%M:%S')}):",
        "",
    ]
    for status, items in bucket_candidates(result.candidates).items():
        if not items:
            continue
        lines.append(f"## {STATUS_LABELS.get(status, status)}")
        for index, candidate in enumerate(items, start=1):
            lines.extend(_format_candidate_plain_lines(index, candidate))
    return "\n".join(lines).rstrip() + "\n"


def render_seed_markdown(
    result: SourceSeedResult,
    *,
    use_llm_brief: bool = False,
    on_warning: Callable[[str], None] | None = None,
) -> str:
    fallback = render_seed_brief_markdown(result)
    if not use_llm_brief or not result.candidates:
        return fallback
    try:
        return _render_seed_llm_markdown(result, fallback)
    except Exception as exc:
        if on_warning:
            on_warning(f"LLM 源头总结失败，已使用本地短版: {exc}")
        return fallback


def render_seed_brief_markdown(result: SourceSeedResult) -> str:
    label = seed_window_label(result)
    lines = [
        f"# 源头雷达 · {result.as_of_time.strftime('%m-%d %H:%M')}",
        "",
        f"{label}，扫描 {result.scanned_messages} 条，"
        f"筛出 {result.candidate_count} 个候选。",
    ]
    if not result.candidates:
        hidden = result.hidden_count
        suffix = f"已隐藏 {hidden} 个旧主题。" if hidden else ""
        lines.append(f"本窗口暂时没有值得追问的新源头。{suffix}")
        return "\n".join(lines) + "\n"

    focus_candidates = _select_brief_candidates(result.candidates)
    lines.append("")
    for index, candidate in enumerate(focus_candidates, start=1):
        lines.append(f"{index}. {_format_brief_candidate(candidate)}")
    omitted = max(len(result.candidates) - len(focus_candidates), 0)
    if omitted:
        lines += ["", f"其余 {omitted} 个低优先级候选已省略。"]
    return "\n".join(lines) + "\n"


def render_seed_detail_markdown(result: SourceSeedResult) -> str:
    label = seed_window_label(result)
    lines = [
        f"# 源头雷达 · {label}",
        "",
        f"- 证据截止：{result.as_of_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 历史回看：{result.lookback_days} 天",
        f"- 扫描消息数：{result.scanned_messages}",
        f"- 源头候选数：{result.candidate_count}",
        "",
    ]
    if not result.candidates:
        hidden = result.hidden_count
        suffix = (
            f"已隐藏 {hidden} 个 old_theme/crowded，可加 --include-closed 查看。"
            if hidden
            else ""
        )
        lines.append(f"> 本窗口未发现可行动源头候选。{suffix}")
        return "\n".join(lines) + "\n"

    lines += [f"## TOP {len(result.candidates)}", ""]
    for status, items in bucket_candidates(result.candidates).items():
        if not items:
            continue
        lines += [
            f"### {STATUS_LABELS.get(status, status)}",
            "",
            "| # | 新组合 | 结构 | 新颖度 | 早期度 | as_of 扩散 | 接力/个股 |",
            "|--:|----|------|-----:|-----:|------|------|",
        ]
        for index, candidate in enumerate(items, start=1):
            stocks = (
                "、".join(candidate.mapped_stocks[:4])
                if candidate.mapped_stocks
                else "—"
            )
            lines.append(
                f"| {index} | {candidate.novel_span} | "
                f"{candidate.anchor_span}+{candidate.modifier_span} | "
                f"{candidate.novelty_strength} | {candidate.earliness_score} | "
                f"{candidate.asof_mentions}次/{candidate.asof_groups}群 | "
                f"{candidate.followup_senders}人/"
                f"{candidate.followup_groups}群/{stocks} |"
            )
        lines.append("")

    lines += ["## 明细", ""]
    for index, candidate in enumerate(result.candidates, start=1):
        first = candidate.first.row.message
        lines.append(f"### {index}. {candidate.novel_span}（{candidate.status}）")
        lines.append(
            f"- 结构：anchor={candidate.anchor_span}，"
            f"modifier={candidate.modifier_span}，"
            f"relation={candidate.relation_type}"
        )
        lines.append(
            "- 历史："
            f"anchor {candidate.prior_anchor_mentions} 次，"
            f"modifier {candidate.prior_modifier_mentions} 次，"
            f"exact {candidate.prior_exact_mentions} 次，"
            f"combo {candidate.prior_combo_mentions} 次"
        )
        lines.append(
            f"- as_of：{candidate.asof_mentions}次/"
            f"{candidate.asof_groups}群/{candidate.asof_senders}人；"
            f"接力 {candidate.followup_senders}人/{candidate.followup_groups}群"
        )
        if candidate.mapped_stocks:
            lines.append(f"- 个股映射：{'、'.join(candidate.mapped_stocks[:8])}")
        lines.append(
            f"- 首现：{first.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"{first.source}/{first.group_name or '-'} / {first.sender}"
        )
        lines.append(f"- 摘要：{snippet(first.raw_content)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _format_candidate_plain_lines(
    index: int,
    candidate: SourceSeedCandidate,
) -> list[str]:
    first = candidate.first.row.message
    stocks = (
        "，个股=" + "、".join(candidate.mapped_stocks[:6])
        if candidate.mapped_stocks
        else ""
    )
    return [
        f"{index}. {candidate.novel_span}  status={candidate.status}  "
        f"score={candidate.score}  ask={candidate.askability_score}",
        f"   结构: anchor={candidate.anchor_span} / "
        f"modifier={candidate.modifier_span} / relation={candidate.relation_type}",
        "   历史: "
        f"anchor={candidate.prior_anchor_mentions}，"
        f"modifier={candidate.prior_modifier_mentions}，"
        f"exact={candidate.prior_exact_mentions}，"
        f"combo={candidate.prior_combo_mentions}",
        "   截至as_of: "
        f"{candidate.asof_mentions}次/{candidate.asof_groups}群/"
        f"{candidate.asof_senders}人；"
        f"接力={candidate.followup_senders}人/{candidate.followup_groups}群"
        f"{stocks}",
        "   首现: "
        f"{first.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{first.source}/{first.group_name or '-'} / {first.sender}",
        f"   摘要: {snippet(first.raw_content)}",
        "",
    ]


def _render_seed_llm_markdown(result: SourceSeedResult, fallback: str) -> str:
    from stock_news.common.llm.client import chat, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    provider_name, _ = get_provider_for_task("source_brief")
    messages = render_prompt_messages(
        "source_brief",
        detail_markdown=render_seed_detail_markdown(result),
    )
    markdown = chat(
        messages,
        provider_name=provider_name,
        temperature=0.2,
        max_tokens=800,
        disable_thinking=True,
    )
    markdown = _normalize_llm_markdown(markdown)
    if not markdown:
        raise ValueError("LLM 返回为空")
    if not markdown.startswith("#"):
        title = fallback.splitlines()[0]
        markdown = f"{title}\n\n{markdown}"
    markdown = _ensure_numbered_brief_items(markdown)
    return markdown.rstrip() + "\n"


def _normalize_llm_markdown(markdown: str) -> str:
    markdown = markdown.strip()
    if markdown.startswith("```"):
        lines = markdown.splitlines()
        if len(lines) >= 2:
            markdown = "\n".join(lines[1:-1]).strip()
    return markdown


def _ensure_numbered_brief_items(markdown: str) -> str:
    lines = markdown.splitlines()
    numbered_count = sum(1 for line in lines if _is_numbered_line(line.strip()))
    if numbered_count >= 2:
        return markdown

    output: list[str] = []
    index = 1
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output.append(line)
            continue
        if _is_numbered_line(stripped):
            output.append(line)
            index += 1
            continue
        output.append(f"{index}. {stripped}")
        index += 1
    return "\n".join(output)


def _is_numbered_line(line: str) -> bool:
    return len(line) > 3 and line[0].isdigit() and line[1] == "." and line[2] == " "


def _select_brief_candidates(
    candidates: tuple[SourceSeedCandidate, ...],
) -> tuple[SourceSeedCandidate, ...]:
    selected: list[SourceSeedCandidate] = []
    selected_ids: set[str] = set()
    for status in STATUS_ORDER:
        if status not in ACTIONABLE_STATUSES:
            continue
        item = next((item for item in candidates if item.status == status), None)
        if item is None:
            continue
        selected.append(item)
        selected_ids.add(item.signal_id)
        if len(selected) >= BRIEF_MARKDOWN_LIMIT:
            return tuple(selected)
    for item in candidates:
        if item.signal_id in selected_ids:
            continue
        selected.append(item)
        if len(selected) >= BRIEF_MARKDOWN_LIMIT:
            break
    return tuple(selected)


def _format_brief_candidate(candidate: SourceSeedCandidate) -> str:
    status = STATUS_LABELS.get(candidate.status, candidate.status)
    first_time = candidate.first.row.message.message_time.strftime("%H:%M")
    spread = (
        f"{candidate.asof_mentions}次/{candidate.asof_groups}群/"
        f"{candidate.asof_senders}人"
    )
    followup = (
        f"，接力 {candidate.followup_senders}人/{candidate.followup_groups}群"
        if candidate.followup_senders or candidate.followup_groups
        else ""
    )
    stocks = (
        f"，个股 {'、'.join(candidate.mapped_stocks[:3])}"
        if candidate.mapped_stocks
        else ""
    )
    if candidate.status == "source_seed":
        action = f"先问 {candidate.anchor_span}+{candidate.modifier_span} 是不是新线索"
    elif candidate.status == "spreading_watch":
        action = "已有扩散，重点确认是否继续跨群接力"
    elif candidate.status == "mapped":
        action = "已映射个股，重点确认能否形成交易主线"
    else:
        action = f"关注 {candidate.anchor_span}+{candidate.modifier_span}"
    return (
        f"**{candidate.novel_span}**：{status}，{first_time} 首现；"
        f"{action}；当前 {spread}{followup}{stocks}。"
    )
