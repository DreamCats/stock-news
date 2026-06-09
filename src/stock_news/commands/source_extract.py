"""阶段二源头结构抽取命令适配层."""

from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import click

from stock_news.common.config import load
from stock_news.common.exceptions import ConfigError
from stock_news.common.llm.task_pool import resolve_provider_pool, select_provider
from stock_news.common.storage import load_messages
from stock_news.models import AppConfig, RawMessage
from stock_news.source import extraction
from stock_news.source.models import SourceStructureItem
from stock_news.source.storage import (
    load_processed_ids,
    load_source_structures,
    save_source_structures,
    structures_path,
    structures_processed_ids_path,
)
from stock_news.source.utils import load_classified_map, parse_date

SOURCE_EXTRACT_BATCH_SIZE = extraction.SOURCE_EXTRACT_BATCH_SIZE
SOURCE_EXTRACT_MAX_WORKERS = extraction.SOURCE_EXTRACT_MAX_WORKERS

# 兼容旧测试/临时调用。
_eligible_messages = extraction.eligible_messages
_extract_batch_by_llm = extraction.extract_batch_by_llm
_looks_promising_for_source_extract = extraction.looks_promising_for_source_extract
_structure_from_llm = extraction.structure_from_llm


def _source_extract_provider_pool(
    cfg: AppConfig,
    provider_name: str | None,
) -> tuple[str | None, ...]:
    try:
        return resolve_provider_pool(cfg, "source_extract", provider_name)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


def _select_provider(
    providers: tuple[str | None, ...],
    batch_index: int,
) -> str | None:
    return select_provider(providers, batch_index)


def _classified_path(data_dir: str, dt: date) -> Path:
    return (
        Path(data_dir).expanduser() / dt.isoformat() / "classified" / "classified.json"
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
        _reset_source_extract_outputs(cfg.storage.data_dir, dt)

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
    new_messages = extraction.eligible_messages(
        messages,
        classified,
        processed_ids,
        min_confidence,
        max_message_chars,
    )
    if limit is not None:
        new_messages = new_messages[:limit]

    if not new_messages:
        _handle_no_new_messages(
            cfg.storage.data_dir,
            dt,
            existing_items,
            processed_ids,
            json_output,
        )
        return

    batches = _message_batches(new_messages)
    _echo_extract_start(dt, new_messages, batches, providers, json_output)

    _run_extract_batches(
        cfg.storage.data_dir,
        dt,
        existing_items,
        processed_ids,
        batches,
        providers,
        json_output,
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
        return

    path = structures_path(cfg.storage.data_dir, dt)
    click.echo(
        f"{dt} 源头结构抽取完成：新增 {len(new_messages)} 条，"
        f"候选 {len(candidates)} 个，保存 {path}"
    )


def _reset_source_extract_outputs(data_dir: str, dt: date) -> None:
    for path in (
        structures_path(data_dir, dt, create=False),
        structures_processed_ids_path(data_dir, dt, create=False),
    ):
        if path.exists():
            path.unlink()


def _handle_no_new_messages(
    data_dir: str,
    dt: date,
    existing_items: list[SourceStructureItem],
    processed_ids: set[str],
    json_output: bool,
) -> None:
    if not structures_path(data_dir, dt, create=False).exists():
        save_source_structures(data_dir, dt, existing_items, processed_ids)
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
        return
    candidates = [item for item in existing_items if item.is_candidate]
    click.echo(f"{message}（已有 {len(candidates)} 个结构候选）")


def _message_batches(
    new_messages: list[RawMessage],
) -> list[list[tuple[int, RawMessage]]]:
    indexed = list(enumerate(new_messages))
    return [
        indexed[index : index + SOURCE_EXTRACT_BATCH_SIZE]
        for index in range(0, len(indexed), SOURCE_EXTRACT_BATCH_SIZE)
    ]


def _echo_extract_start(
    dt: date,
    new_messages: list[RawMessage],
    batches: list[list[tuple[int, RawMessage]]],
    providers: tuple[str | None, ...],
    json_output: bool,
) -> None:
    if json_output:
        return
    provider_text = ",".join(item or "task/default" for item in providers)
    workers = min(SOURCE_EXTRACT_MAX_WORKERS, len(batches), len(providers))
    click.echo(
        f"{dt} 源头结构抽取：新增 {len(new_messages)} 条，"
        f"batches={len(batches)}，workers={workers}，provider={provider_text}",
        err=True,
    )


def _run_extract_batches(
    data_dir: str,
    dt: date,
    existing_items: list[SourceStructureItem],
    processed_ids: set[str],
    batches: list[list[tuple[int, RawMessage]]],
    providers: tuple[str | None, ...],
    json_output: bool,
) -> None:
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
                executor.submit(
                    extraction.extract_batch_by_llm,
                    batch,
                    selected_provider,
                )
            ] = (batch_index, batch, selected_provider)
        for future in as_completed(futures):
            batch_index, batch, selected_provider = futures[future]
            extracted_by_index = _batch_result(
                future,
                batch_index,
                len(batches),
                json_output,
            )
            batch_candidates = _append_batch_items(
                existing_items,
                processed_ids,
                batch,
                extracted_by_index,
                selected_provider,
            )
            save_source_structures(data_dir, dt, existing_items, processed_ids)
            completed_batches += 1
            total_candidates += batch_candidates
            if not json_output:
                click.echo(
                    f"  进度 {completed_batches}/{len(batches)} batches，"
                    f"本批候选 {batch_candidates}，累计候选 {total_candidates}",
                    err=True,
                )


def _batch_result(
    future: Future[dict[int, SourceStructureItem]],
    batch_index: int,
    batch_count: int,
    json_output: bool,
) -> dict[int, SourceStructureItem]:
    try:
        return future.result()
    except Exception as exc:
        if not json_output:
            click.echo(f"  batch {batch_index + 1}/{batch_count} 失败: {exc}", err=True)
        return {}


def _append_batch_items(
    existing_items: list[SourceStructureItem],
    processed_ids: set[str],
    batch: list[tuple[int, RawMessage]],
    extracted_by_index: dict[int, SourceStructureItem],
    selected_provider: str | None,
) -> int:
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
    return batch_candidates
