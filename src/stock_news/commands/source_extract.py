"""源头雷达候选抽取."""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import date

import click

from stock_news.commands.analyze._common import load_classified, parse_date
from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import AppConfig, MessageCategory, RawMessage
from stock_news.source.models import SourceExtractItem
from stock_news.source.storage import (
    candidates_path,
    load_processed_ids,
    load_source_extracts,
    save_source_extracts,
)

SOURCE_EXTRACT_BATCH_SIZE = 16
CONCURRENCY = 8
SOURCE_TYPES = {
    "new_concept",
    "new_application",
    "policy_catalyst",
    "industry_change",
    "noise",
}


def _as_confidence(value: object, default: float = 0.5) -> float:
    try:
        confidence = float(str(value))
    except (TypeError, ValueError):
        return default
    return min(max(confidence, 0.0), 1.0)


def _clean_terms(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    for item in value:
        term = str(item or "").strip()
        if 2 <= len(term) <= 24 and term not in terms:
            terms.append(term)
    return terms[:3]


def _extract_item_from_llm(
    msg: RawMessage,
    item: dict[str, object],
    provider_name: str,
) -> SourceExtractItem:
    source_type = str(item.get("source_type") or "noise").strip()
    if source_type not in SOURCE_TYPES:
        source_type = "noise"
    terms = _clean_terms(item.get("terms"))
    is_candidate = bool(item.get("is_source_candidate")) and bool(terms)
    if not is_candidate:
        source_type = "noise"

    reject_reason = item.get("reject_reason")
    evidence = item.get("evidence")
    return SourceExtractItem(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        group_name=msg.group_name,
        is_source_candidate=is_candidate,
        source_type=source_type,  # type: ignore[arg-type]
        terms=terms if is_candidate else [],
        clean_title=str(item.get("clean_title") or "").strip(),
        confidence=_as_confidence(item.get("confidence")),
        reject_reason=str(reject_reason).strip() if reject_reason else None,
        evidence=str(evidence).strip() if evidence else None,
        llm_provider=provider_name,
    )


def _extract_one_by_llm(
    msg: RawMessage,
    provider_name: str | None,
) -> SourceExtractItem:
    from stock_news.common.llm.client import chat_json, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("source_extract")

    messages = render_prompt_messages(
        "source_extract",
        sender=msg.sender,
        raw_content=msg.raw_content,
    )
    result = chat_json(messages, provider_name=provider_name, disable_thinking=True)
    if not isinstance(result, dict):
        result = {}
    return _extract_item_from_llm(msg, result, provider_name)


def _extract_batch_by_llm(
    batch: list[tuple[int, RawMessage]],
    provider_name: str | None,
) -> dict[int, SourceExtractItem]:
    from stock_news.common.llm.client import chat_json_list, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("source_extract")

    lines: list[str] = []
    idx_map: dict[int, tuple[int, RawMessage]] = {}
    for seq, (orig_idx, msg) in enumerate(batch, 1):
        lines.append(f"[{seq}] 发送人: {msg.sender}\n{msg.raw_content[:500]}")
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

    out: dict[int, SourceExtractItem] = {}
    for item in results:
        if not isinstance(item, dict) or "index" not in item:
            continue
        raw_index = item["index"]
        if not isinstance(raw_index, int | str):
            continue
        try:
            seq = int(raw_index)
        except ValueError:
            continue
        if seq not in idx_map:
            continue
        orig_idx, msg = idx_map[seq]
        out[orig_idx] = _extract_item_from_llm(msg, item, provider_name)
    return out


def _research_message_ids(
    cfg_data_dir: str,
    dt: date,
    min_confidence: float,
) -> set[str]:
    classified = load_classified(cfg_data_dir, dt)
    return {
        item.message_id
        for item in classified
        if item.category == MessageCategory.RESEARCH
        and item.confidence >= min_confidence
    }


def _source_extract_provider_pool(cfg: AppConfig) -> tuple[str, ...]:
    providers = tuple(cfg.llm.provider_pools.get("source_extract") or ())
    missing = [name for name in providers if name not in cfg.llm.providers]
    if missing:
        raise click.ClickException(
            "source_extract provider_pools 包含未配置 provider: " + ", ".join(missing)
        )
    return providers


def _select_provider(provider_pool: tuple[str, ...], index: int) -> str | None:
    if not provider_pool:
        return None
    return provider_pool[index % len(provider_pool)]


def extract_source_candidates(
    date_str: str,
    min_confidence: float,
    json_output: bool,
) -> None:
    cfg = load()
    dt = parse_date(date_str)
    providers = _source_extract_provider_pool(cfg)

    from stock_news.common.llm.prompts import ensure_prompts_dir

    ensure_prompts_dir()

    research_ids = _research_message_ids(cfg.storage.data_dir, dt, min_confidence)
    if not research_ids:
        message = f"{dt} 无可抽取的 research 分类消息，请先运行 sn analyze classify"
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {"date": dt.isoformat(), "candidates": []},
                        "message": message,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(message)
        return

    existing_items = load_source_extracts(cfg.storage.data_dir, dt)
    processed_ids = load_processed_ids(cfg.storage.data_dir, dt)
    messages = load_messages(cfg.storage.data_dir, dt)
    new_messages = [
        msg
        for msg in messages
        if msg.message_id in research_ids and msg.message_id not in processed_ids
    ]

    if not new_messages:
        candidates = [item for item in existing_items if item.is_source_candidate]
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "date": dt.isoformat(),
                            "new": 0,
                            "total": len(existing_items),
                            "candidate_count": len(candidates),
                            "candidates": [
                                item.model_dump(mode="json") for item in candidates
                            ],
                        },
                        "message": (
                            f"无新 research 消息需抽取，已有 {len(candidates)} 个候选"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(
                f"{dt} 无新 research 消息需抽取（已有 {len(candidates)} 个候选）"
            )
        return

    if not json_output:
        provider_text = ",".join(providers) if providers else "task/default"
        click.echo(
            f"  已有 {len(existing_items)} 条源头抽取结果，"
            f"新增 {len(new_messages)} 条待抽取，provider={provider_text}",
            err=True,
        )

    indexed = list(enumerate(new_messages))
    batches = [
        indexed[i : i + SOURCE_EXTRACT_BATCH_SIZE]
        for i in range(0, len(indexed), SOURCE_EXTRACT_BATCH_SIZE)
    ]

    extract_map: dict[int, SourceExtractItem] = {}
    committed: set[int] = set()
    done_msgs = 0
    write_lock = threading.Lock()

    def _save_snapshot() -> None:
        with write_lock:
            save_source_extracts(
                cfg.storage.data_dir,
                dt,
                existing_items,
                processed_ids,
            )

    def _commit_indices(indices: list[int]) -> None:
        new_committed = [idx for idx in indices if idx not in committed]
        if not new_committed:
            return
        for idx in new_committed:
            existing_items.append(extract_map[idx])
            processed_ids.add(new_messages[idx].message_id)
            committed.add(idx)
        _save_snapshot()

    def _fallback_one(
        idx: int,
        msg: RawMessage,
        selected_provider: str | None,
    ) -> tuple[int, SourceExtractItem]:
        return idx, _extract_one_by_llm(msg, selected_provider)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {}
        for batch_index, batch in enumerate(batches):
            selected_provider = _select_provider(providers, batch_index)
            if not json_output:
                start_no = batch[0][0] + 1
                end_no = batch[-1][0] + 1
                provider_text = selected_provider or "task/default"
                click.echo(
                    f"  批次 {batch_index + 1}/{len(batches)} "
                    f"[{start_no}-{end_no}] -> {provider_text}",
                    err=True,
                )
            futures[pool.submit(_extract_batch_by_llm, batch, selected_provider)] = (
                batch_index,
                batch,
                selected_provider,
            )
        fallback_futures: dict[
            Future[tuple[int, SourceExtractItem]],
            tuple[int, RawMessage, str | None],
        ] = {}

        for future in as_completed(futures):
            batch_index, batch, selected_provider = futures[future]
            provider_text = selected_provider or "task/default"
            try:
                batch_results = future.result()
                extract_map.update(batch_results)
            except Exception as exc:
                batch_results = {}
                if not json_output:
                    click.echo(
                        f"    批次 {batch_index + 1}/{len(batches)} "
                        f"{provider_text} 批量源头抽取异常: {exc}",
                        err=True,
                    )
            missed = [(idx, msg) for idx, msg in batch if idx not in extract_map]
            done_msgs += len(batch) - len(missed)
            if not json_output:
                success_count = len(batch) - len(missed)
                click.echo(
                    f"  批次 {batch_index + 1}/{len(batches)} "
                    f"{provider_text} 完成 {success_count}/{len(batch)}，"
                    f"已抽取 {done_msgs}/{len(new_messages)}...",
                    err=True,
                )
            _commit_indices([idx for idx, _msg in batch if idx in extract_map])
            for idx, msg in missed:
                selected_provider = _select_provider(providers, idx)
                if not json_output:
                    retry_provider_text = selected_provider or "task/default"
                    click.echo(
                        f"    重试消息 {idx + 1}/{len(new_messages)} "
                        f"-> {retry_provider_text}",
                        err=True,
                    )
                fallback_futures[
                    pool.submit(_fallback_one, idx, msg, selected_provider)
                ] = (idx, msg, selected_provider)

        for fallback in as_completed(fallback_futures):
            idx, _msg, selected_provider = fallback_futures[fallback]
            provider_text = selected_provider or "task/default"
            try:
                idx, item = fallback.result()
            except Exception as exc:
                if not json_output:
                    click.echo(
                        f"    消息 {idx + 1}/{len(new_messages)} "
                        f"{provider_text} 逐条源头抽取异常: {exc}",
                        err=True,
                    )
                continue
            extract_map[idx] = item
            done_msgs += 1
            if not json_output:
                click.echo(
                    f"  消息 {idx + 1}/{len(new_messages)} "
                    f"{provider_text} 重试完成，"
                    f"已抽取 {done_msgs}/{len(new_messages)}...",
                    err=True,
                )
            _commit_indices([idx])

    new_items = [extract_map[idx] for idx in sorted(extract_map)]
    new_candidates = [item for item in new_items if item.is_source_candidate]
    all_candidates = [item for item in existing_items if item.is_source_candidate]
    out_path = candidates_path(cfg.storage.data_dir, dt)

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": dt.isoformat(),
                        "new_messages": len(new_messages),
                        "new_candidates": len(new_candidates),
                        "total": len(existing_items),
                        "candidate_count": len(all_candidates),
                        "candidates": [
                            item.model_dump(mode="json") for item in all_candidates
                        ],
                    },
                    "message": (
                        f"源头抽取完成，新增 {len(new_candidates)} 个候选，"
                        f"总计 {len(all_candidates)} 个候选"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        click.echo(
            f"\n{dt} 源头抽取完成: 新增 {len(new_candidates)} 个候选，"
            f"总计 {len(all_candidates)} 个候选"
        )
        click.echo(f"结果已保存: {out_path}")
