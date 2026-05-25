"""消息分类：规则关键词降级 + LLM 单/批模式."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import click

from stock_news.commands.analyze._common import (
    classified_dir,
    load_classified,
    parse_date,
)
from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import ClassifiedMessage, MessageCategory, RawMessage

CLASSIFY_BATCH_SIZE = 16
CONCURRENCY = 8

_RECOMMENDATION_PATTERNS = [
    r"推荐", r"买入", r"加仓", r"关注", r"看好", r"看多",
    r"目标价", r"低吸", r"低开可", r"弹性大", r"短线",
    r"重点关注", r"继续推", r"逻辑不变", r"可以介入",
]

_EVENT_PATTERNS = [
    r"策略会", r"调研", r"电话会", r"会议", r"路演",
    r"活动", r"报名", r"直播", r"论坛",
]

_TOOL_PATTERNS = [
    r"软件", r"工具", r"试用", r"订阅", r"开通",
    r"下载", r"注册", r"app",
]


def _msg_fields(msg: RawMessage) -> dict:
    return {"source": msg.source, "sender": msg.sender, "message_time": msg.message_time}


def _classify_by_rules(msg: RawMessage) -> ClassifiedMessage:
    content = msg.raw_content
    common = _msg_fields(msg)
    for p in _RECOMMENDATION_PATTERNS:
        if re.search(p, content):
            return ClassifiedMessage(
                message_id=msg.message_id,
                **common,
                category=MessageCategory.RECOMMENDATION,
                confidence=0.6,
                reason=f"命中关键词: {p}",
            )
    for p in _EVENT_PATTERNS:
        if re.search(p, content):
            return ClassifiedMessage(
                message_id=msg.message_id,
                **common,
                category=MessageCategory.EVENT,
                confidence=0.6,
                reason=f"命中关键词: {p}",
            )
    for p in _TOOL_PATTERNS:
        if re.search(p, content, re.IGNORECASE):
            return ClassifiedMessage(
                message_id=msg.message_id,
                **common,
                category=MessageCategory.TOOL,
                confidence=0.5,
                reason=f"命中关键词: {p}",
            )
    if len(content) > 50:
        return ClassifiedMessage(
            message_id=msg.message_id,
            **common,
            category=MessageCategory.RESEARCH,
            confidence=0.4,
            reason="无明确推荐关键词，内容较长归为研究",
        )
    return ClassifiedMessage(
        message_id=msg.message_id,
        **common,
        category=MessageCategory.NOISE,
        confidence=0.4,
        reason="短消息且无有效关键词",
    )


def _classify_by_llm(msg: RawMessage, provider_name: str | None) -> ClassifiedMessage:
    from stock_news.common.llm.client import chat_json, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("classify")

    prompt = render_prompt(
        "classify",
        source=msg.source,
        sender=msg.sender,
        raw_content=msg.raw_content,
    )
    result = chat_json(
        [{"role": "user", "content": prompt}],
        provider_name=provider_name,
        disable_thinking=True,
    )
    category_str = str(result.get("category", "noise"))
    try:
        category = MessageCategory(category_str)
    except ValueError:
        category = MessageCategory.NOISE

    return ClassifiedMessage(
        message_id=msg.message_id,
        **_msg_fields(msg),
        category=category,
        confidence=float(result.get("confidence", 0.5)),
        reason=str(result.get("reason", "")),
        llm_provider=provider_name,
    )


def _classify_batch_by_llm(
    batch: list[tuple[int, RawMessage]],
    provider_name: str | None,
) -> dict[int, ClassifiedMessage]:
    """批量分类，返回 {原始index: ClassifiedMessage}."""
    from stock_news.common.llm.client import chat_json_list, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("classify")

    lines: list[str] = []
    idx_map: dict[int, tuple[int, RawMessage]] = {}
    for seq, (orig_idx, msg) in enumerate(batch, 1):
        lines.append(f"[{seq}] 来源: {msg.source}, 发送人: {msg.sender}\n{msg.raw_content[:500]}")
        idx_map[seq] = (orig_idx, msg)

    prompt = render_prompt("classify_batch", messages="\n\n".join(lines))
    results = chat_json_list(
        [{"role": "user", "content": prompt}],
        provider_name=provider_name,
        disable_thinking=True,
    )

    out: dict[int, ClassifiedMessage] = {}
    for item in results:
        if not isinstance(item, dict) or "index" not in item:
            continue
        seq = int(item["index"])
        if seq not in idx_map:
            continue
        orig_idx, msg = idx_map[seq]
        category_str = str(item.get("category", "noise"))
        try:
            category = MessageCategory(category_str)
        except ValueError:
            category = MessageCategory.NOISE
        out[orig_idx] = ClassifiedMessage(
            message_id=msg.message_id,
            **_msg_fields(msg),
            category=category,
            confidence=float(item.get("confidence", 0.5)),
            reason=str(item.get("reason", "")),
            llm_provider=provider_name,
        )
    return out


def classify(
    date_str: str,
    no_llm: bool,
    provider_name: str | None,
    json_output: bool,
) -> None:
    cfg = load()
    dt = parse_date(date_str)
    messages = load_messages(cfg.storage.data_dir, dt)

    if not messages:
        if json_output:
            click.echo(json.dumps({"ok": True, "data": {"date": dt.isoformat(), "total": 0, "classified": []}, "message": f"{dt} 无消息"}, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{dt} 无消息可分类")
        return

    existing = load_classified(cfg.storage.data_dir, dt)
    existing_map = {c.message_id: c for c in existing}
    new_messages = [m for m in messages if m.message_id not in existing_map]

    if not new_messages:
        results = list(existing_map.values())
        if json_output:
            counts: dict[str, int] = {}
            for r in results:
                counts[r.category.value] = counts.get(r.category.value, 0) + 1
            click.echo(json.dumps({
                "ok": True,
                "data": {
                    "date": dt.isoformat(),
                    "total": len(results),
                    "new": 0,
                    "distribution": counts,
                    "classified": [r.model_dump(mode="json") for r in results],
                },
                "message": f"无新消息需分类，已有 {len(results)} 条",
            }, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{dt} 无新消息需分类（已有 {len(existing)} 条分类结果）")
        return

    if not no_llm:
        from stock_news.common.llm.prompts import ensure_prompts_dir
        ensure_prompts_dir()

    if not json_output:
        click.echo(f"  已有 {len(existing)} 条，新增 {len(new_messages)} 条待分类", err=True)

    out_path = classified_dir(cfg.storage.data_dir, dt) / "classified.json"
    all_msg_ids = [m.message_id for m in messages]

    if no_llm:
        new_results = [_classify_by_rules(msg) for msg in new_messages]
        for r in new_results:
            existing_map[r.message_id] = r
        snapshot = [existing_map[mid] for mid in all_msg_ids if mid in existing_map]
        dumped = [r.model_dump(mode="json") for r in snapshot]
        out_path.write_text(
            json.dumps(dumped, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        results_map: dict[int, ClassifiedMessage] = {}

        indexed = list(enumerate(new_messages))
        batches = [indexed[i:i + CLASSIFY_BATCH_SIZE] for i in range(0, len(indexed), CLASSIFY_BATCH_SIZE)]

        if not json_output:
            click.echo(f"  批量模式: {len(batches)} 批 × {CLASSIFY_BATCH_SIZE} 条, 并行 {CONCURRENCY}", err=True)

        def _classify_fallback_one(idx: int, msg: RawMessage) -> tuple[int, ClassifiedMessage]:
            try:
                return idx, _classify_by_llm(msg, provider_name)
            except Exception:
                return idx, _classify_by_rules(msg)

        done_msgs = 0
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {pool.submit(_classify_batch_by_llm, batch, provider_name): batch for batch in batches}
            fallback_futures: dict = {}

            for future in as_completed(futures):
                batch = futures[future]
                try:
                    batch_results = future.result()
                    results_map.update(batch_results)
                except Exception as e:
                    batch_results = {}
                    if not json_output:
                        click.echo(f"    ⚠ 批量分类异常: {e}", err=True)
                missed = [(idx, msg) for idx, msg in batch if idx not in results_map]
                done_msgs += len(batch) - len(missed)
                if not json_output:
                    click.echo(f"  已分类 {done_msgs}/{len(new_messages)}...", err=True)
                if missed:
                    if not json_output:
                        click.echo(f"    ↳ {len(missed)} 条缺失，提交逐条重试...", err=True)
                    for idx, msg in missed:
                        fb = pool.submit(_classify_fallback_one, idx, msg)
                        fallback_futures[fb] = (idx, msg)

                for idx in [i for i, _ in batch if i in results_map]:
                    existing_map[results_map[idx].message_id] = results_map[idx]
                snapshot = [existing_map[mid] for mid in all_msg_ids if mid in existing_map]
                out_path.write_text(
                    json.dumps([r.model_dump(mode="json") for r in snapshot], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            for fb_future in as_completed(fallback_futures):
                idx, classified_msg = fb_future.result()
                results_map[idx] = classified_msg
                existing_map[classified_msg.message_id] = classified_msg
                done_msgs += 1
                if not json_output:
                    click.echo(f"  已分类 {done_msgs}/{len(new_messages)} (重试)...", err=True)

            snapshot = [existing_map[mid] for mid in all_msg_ids if mid in existing_map]
            out_path.write_text(
                json.dumps([r.model_dump(mode="json") for r in snapshot], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        new_results = [results_map[i] for i in range(len(new_messages))]

    if not json_output:
        click.echo(f"  已分类 {len(new_results)}/{len(new_messages)}...", err=True)

    results = [existing_map[mid] for mid in [m.message_id for m in messages] if mid in existing_map]

    counts = {}
    for r in results:
        counts[r.category.value] = counts.get(r.category.value, 0) + 1

    if json_output:
        click.echo(json.dumps({
            "ok": True,
            "data": {
                "date": dt.isoformat(),
                "total": len(results),
                "new": len(new_results),
                "existing": len(existing),
                "distribution": counts,
                "classified": [r.model_dump(mode="json") for r in results],
            },
            "message": f"分类完成，新增 {len(new_results)} 条，总计 {len(results)} 条",
        }, ensure_ascii=False, indent=2))
    else:
        click.echo(f"\n{dt} 分类完成: 新增 {len(new_results)} 条，总计 {len(results)} 条")
        for cat, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            click.echo(f"  {cat}: {cnt} 条")
        click.echo(f"\n结果已保存: {out_path}")
