"""阶段二源头结构抽取：LLM 只负责拆 span，不判断新旧."""

from __future__ import annotations

import json
import re
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import click

from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import AppConfig, ClassifiedMessage, MessageCategory, RawMessage
from stock_news.source.models import SourceStructureItem
from stock_news.source.storage import (
    load_processed_ids,
    load_source_structures,
    save_source_structures,
    structures_path,
    structures_processed_ids_path,
)
from stock_news.source.utils import load_classified_map, parse_date

SOURCE_EXTRACT_BATCH_SIZE = 10
SOURCE_EXTRACT_MAX_WORKERS = 4
SOURCE_RELATIONS = {
    "A化B",
    "prefix-anchor",
    "modifier-anchor",
    "anchor-extension",
    "other",
}
SOURCE_CATEGORIES = {
    MessageCategory.RESEARCH.value,
    MessageCategory.EVENT.value,
}
SOURCE_CUES = (
    "新概念",
    "新方向",
    "新题材",
    "新应用",
    "新场景",
    "从0到1",
    "0到1",
    "预期差",
    "拐点",
    "突破",
    "替代",
    "瓶颈",
    "新路线",
    "新技术",
    "新工艺",
    "产业趋势",
    "商业化",
    "国产化",
    "半导体化",
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
    "公告速递",
    "业绩交流",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _contains_span(text: str, span: str) -> bool:
    if not span:
        return False
    return span in text or _normalize_text(span) in _normalize_text(text)


def _has_strong_structure(text: str) -> bool:
    compact = _normalize_text(text)
    return bool(
        re.search(
            r"[A-Za-z0-9\u4e00-\u9fff]{2,12}化的?[A-Z][A-Z0-9]{1,10}",
            compact,
        )
        or re.search(
            r"(?<![A-Za-z0-9])[A-Za-z0-9]{2,12}[-/][A-Z][A-Z0-9]{1,10}(?![A-Za-z0-9])",
            compact,
        )
    )


def _looks_promising_for_source_extract(msg: RawMessage) -> bool:
    text = msg.raw_content
    if any(part in text for part in NOISE_SUBSTRINGS):
        return False
    if _has_strong_structure(text):
        return True
    return any(cue in text for cue in SOURCE_CUES)


def _confidence(value: object, default: float = 0.5) -> float:
    try:
        score = float(str(value))
    except (TypeError, ValueError):
        return default
    return min(max(score, 0.0), 1.0)


def _clean_span(value: object, limit: int = 32) -> str:
    span = str(value or "").strip()
    span = re.sub(r"\s+", "", span)
    if len(span) > limit:
        return ""
    return span


def _structure_from_llm(
    msg: RawMessage,
    payload: dict[str, object],
    provider_name: str,
) -> SourceStructureItem:
    relation_type = str(payload.get("relation_type") or "other").strip()
    if relation_type not in SOURCE_RELATIONS:
        relation_type = "other"

    anchor = _clean_span(payload.get("anchor_span"))
    modifier = _clean_span(payload.get("modifier_span"))
    novel = _clean_span(payload.get("novel_span"))
    evidence = str(payload.get("relation_evidence") or "").strip()
    is_candidate = bool(payload.get("is_candidate"))

    reject_reason = payload.get("reject_reason")
    if is_candidate:
        missing = [
            name
            for name, value in (
                ("anchor_span", anchor),
                ("modifier_span", modifier),
                ("novel_span", novel),
            )
            if not _contains_span(msg.raw_content, value)
        ]
        if missing:
            is_candidate = False
            reject_reason = "span 无法回指原文: " + ",".join(missing)
    if not is_candidate:
        anchor = ""
        modifier = ""
        novel = ""
        relation_type = "other"

    return SourceStructureItem(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        group_name=msg.group_name,
        is_candidate=is_candidate,
        anchor_span=anchor,
        modifier_span=modifier,
        novel_span=novel,
        relation_type=relation_type,  # type: ignore[arg-type]
        relation_evidence=evidence if is_candidate else "",
        ask_question=str(payload.get("ask_question") or "").strip()
        if is_candidate
        else "",
        confidence=_confidence(payload.get("confidence")),
        reject_reason=str(reject_reason).strip() if reject_reason else None,
        llm_provider=provider_name,
    )


def _extract_batch_by_llm(
    batch: list[tuple[int, RawMessage]],
    provider_name: str | None,
) -> dict[int, SourceStructureItem]:
    from stock_news.common.llm.client import chat_json_list, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("source_extract")

    lines: list[str] = []
    idx_map: dict[int, tuple[int, RawMessage]] = {}
    for seq, (orig_idx, msg) in enumerate(batch, 1):
        lines.append(
            f"[{seq}] 来源: {msg.source}\n发送人: {msg.sender}\n{msg.raw_content[:900]}"
        )
        idx_map[seq] = (orig_idx, msg)

    messages = render_prompt_messages(
        "source_extract_batch",
        messages="\n\n".join(lines),
    )
    results = chat_json_list(
        messages,
        provider_name=provider_name,
        disable_thinking=True,
    )

    out: dict[int, SourceStructureItem] = {}
    for item in results:
        if not isinstance(item, dict) or "index" not in item:
            continue
        try:
            seq = int(str(item["index"]))
        except ValueError:
            continue
        if seq not in idx_map:
            continue
        orig_idx, msg = idx_map[seq]
        out[orig_idx] = _structure_from_llm(msg, item, provider_name)
    return out


def _source_extract_provider_pool(
    cfg: AppConfig,
    provider_name: str | None,
) -> tuple[str | None, ...]:
    if provider_name:
        if provider_name not in cfg.llm.providers:
            raise click.ClickException(f"LLM provider 不存在: {provider_name}")
        return (provider_name,)

    providers = tuple(cfg.llm.provider_pools.get("source_extract") or ())
    missing = [name for name in providers if name not in cfg.llm.providers]
    if missing:
        raise click.ClickException(
            "source_extract provider_pools 包含未配置 provider: " + ",".join(missing)
        )
    if providers:
        return providers
    routed = cfg.llm.task_routing.get("source_extract")
    if routed:
        return (routed,)
    return (None,)


def _select_provider(
    providers: tuple[str | None, ...],
    batch_index: int,
) -> str | None:
    return providers[batch_index % len(providers)]


def _eligible_messages(
    messages: list[RawMessage],
    classified: dict[str, ClassifiedMessage],
    processed_ids: set[str],
    min_confidence: float,
    max_message_chars: int,
) -> list[RawMessage]:
    out: list[RawMessage] = []
    for msg in messages:
        if msg.message_id in processed_ids:
            continue
        if msg.source not in {"个人群", "个人消息"}:
            continue
        if len(msg.raw_content) > max_message_chars:
            continue
        item = classified.get(msg.message_id)
        if item is None:
            continue
        if item.confidence < min_confidence:
            continue
        if item.category.value not in SOURCE_CATEGORIES:
            continue
        if not _looks_promising_for_source_extract(msg):
            continue
        out.append(msg)
    return out


def _classified_path(data_dir: str, dt: date) -> Path:
    return (
        Path(data_dir).expanduser()
        / dt.isoformat()
        / "classified"
        / "classified.json"
    )


def _summary(dt: date, items: list[SourceStructureItem]) -> dict[str, object]:
    candidates = [item for item in items if item.is_candidate]
    return {
        "date": dt.isoformat(),
        "total": len(items),
        "candidate_count": len(candidates),
        "structures_path": str(structures_path(load().storage.data_dir, dt)),
        "candidates": [item.model_dump(mode="json") for item in candidates],
    }


def extract_source_candidates(
    date_str: str,
    min_confidence: float,
    limit: int | None,
    max_message_chars: int,
    provider_name: str | None,
    reset: bool,
    json_output: bool,
) -> None:
    cfg = load()
    dt = parse_date(date_str)
    providers = _source_extract_provider_pool(cfg, provider_name)

    from stock_news.common.llm.prompts import ensure_prompts_dir

    ensure_prompts_dir()

    if reset:
        for path in (
            structures_path(cfg.storage.data_dir, dt, create=False),
            structures_processed_ids_path(cfg.storage.data_dir, dt, create=False),
        ):
            if path.exists():
                path.unlink()

    existing_items = load_source_structures(cfg.storage.data_dir, dt)
    processed_ids = load_processed_ids(cfg.storage.data_dir, dt)
    messages = load_messages(cfg.storage.data_dir, dt)
    classified = load_classified_map(cfg.storage.data_dir, [dt])
    if (
        messages
        and not classified
        and not _classified_path(cfg.storage.data_dir, dt).exists()
    ):
        raise click.ClickException(
            f"{dt} 缺少 classified/classified.json，"
            f"请先运行: sn analyze classify --date {dt}"
        )
    new_messages = _eligible_messages(
        messages,
        classified,
        processed_ids,
        min_confidence,
        max_message_chars,
    )
    if limit is not None:
        new_messages = new_messages[:limit]

    if not new_messages:
        if not structures_path(cfg.storage.data_dir, dt, create=False).exists():
            save_source_structures(
                cfg.storage.data_dir,
                dt,
                existing_items,
                processed_ids,
            )
        message = f"{dt} 无新消息需要源头结构抽取"
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": _summary(dt, existing_items),
                        "message": message,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            candidates = [item for item in existing_items if item.is_candidate]
            click.echo(f"{message}（已有 {len(candidates)} 个结构候选）")
        return

    indexed = list(enumerate(new_messages))
    batches = [
        indexed[i : i + SOURCE_EXTRACT_BATCH_SIZE]
        for i in range(0, len(indexed), SOURCE_EXTRACT_BATCH_SIZE)
    ]

    if not json_output:
        provider_text = ",".join(item or "task/default" for item in providers)
        workers = min(SOURCE_EXTRACT_MAX_WORKERS, len(batches), len(providers))
        click.echo(
            f"{dt} 源头结构抽取：新增 {len(new_messages)} 条，"
            f"batches={len(batches)}，workers={workers}，provider={provider_text}",
            err=True,
        )

    completed_batches = 0
    total_candidates = len([item for item in existing_items if item.is_candidate])
    max_workers = min(SOURCE_EXTRACT_MAX_WORKERS, len(batches), len(providers))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: dict[
            Future[dict[int, SourceStructureItem]],
            tuple[int, list[tuple[int, RawMessage]], str | None],
        ] = {}
        for batch_index, batch in enumerate(batches):
            selected_provider = _select_provider(providers, batch_index)
            futures[
                executor.submit(_extract_batch_by_llm, batch, selected_provider)
            ] = (batch_index, batch, selected_provider)
        for future in as_completed(futures):
            batch_index, batch, selected_provider = futures[future]
            try:
                extracted_by_index = future.result()
            except Exception as exc:
                extracted_by_index = {}
                if not json_output:
                    click.echo(
                        f"  batch {batch_index + 1}/{len(batches)} 失败: {exc}",
                        err=True,
                    )

            batch_candidates = 0
            for index, msg in batch:
                item = extracted_by_index.get(index)
                if item is None:
                    item = SourceStructureItem(
                        message_id=msg.message_id,
                        source=msg.source,
                        sender=msg.sender,
                        message_time=msg.message_time,
                        group_name=msg.group_name,
                        is_candidate=False,
                        confidence=0.0,
                        reject_reason="LLM 未返回对应 index",
                        llm_provider=selected_provider,
                    )
                if item.is_candidate:
                    batch_candidates += 1
                existing_items.append(item)
                processed_ids.add(msg.message_id)

            save_source_structures(
                cfg.storage.data_dir,
                dt,
                existing_items,
                processed_ids,
            )
            completed_batches += 1
            total_candidates += batch_candidates
            if not json_output:
                click.echo(
                    f"  进度 {completed_batches}/{len(batches)} batches，"
                    f"本批候选 {batch_candidates}，累计候选 {total_candidates}",
                    err=True,
                )

    candidates = [item for item in existing_items if item.is_candidate]

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": _summary(dt, existing_items),
                    "message": (
                        f"新增抽取 {len(new_messages)} 条，候选 {len(candidates)} 个"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        path = structures_path(cfg.storage.data_dir, dt)
        click.echo(
            f"{dt} 源头结构抽取完成：新增 {len(new_messages)} 条，"
            f"候选 {len(candidates)} 个，保存 {path}"
        )
