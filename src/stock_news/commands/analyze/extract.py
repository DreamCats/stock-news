"""推荐抽取：从 RECOMMENDATION 类消息抽取结构化字段."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import click

from stock_news.commands.analyze._common import (
    extracted_dir,
    load_classified,
    load_recommendations,
    parse_date,
)
from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import MessageCategory, RawMessage, Recommendation

EXTRACT_BATCH_SIZE = 16
CONCURRENCY = 8


def _load_extracted_ids(cfg_data_dir: str, dt: date) -> set[str]:
    path = extracted_dir(cfg_data_dir, dt) / "processed_ids.json"
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_extracted_ids(cfg_data_dir: str, dt: date, ids: set[str]) -> None:
    path = extracted_dir(cfg_data_dir, dt) / "processed_ids.json"
    path.write_text(json.dumps(sorted(ids), ensure_ascii=False), encoding="utf-8")


def _extract_by_llm(
    msg: RawMessage, provider_name: str | None
) -> list[Recommendation]:
    from stock_news.common.llm.client import chat_json, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("extract")

    prompt = render_prompt(
        "extract",
        sender=msg.sender,
        raw_content=msg.raw_content,
    )
    result = chat_json(
        [{"role": "user", "content": prompt}],
        provider_name=provider_name,
        disable_thinking=True,
    )

    items = result if isinstance(result, list) else [result]
    recs: list[Recommendation] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        recs.append(
            Recommendation(
                message_id=msg.message_id,
                source=msg.source,
                sender=msg.sender,
                message_time=msg.message_time,
                ticker=str(item.get("ticker", "")),
                market=item.get("market"),
                action=str(item.get("action", "关注")),
                strength=str(item.get("strength", "中")),
                horizon=item.get("horizon"),
                reasoning=item.get("reasoning"),
                risk_note=item.get("risk_note"),
                raw_content=msg.raw_content,
            )
        )
    return recs


def _extract_batch_by_llm(
    batch: list[tuple[int, RawMessage]],
    provider_name: str | None,
) -> dict[int, list[Recommendation]]:
    """批量抽取，返回 {原始index: [Recommendation]}."""
    from stock_news.common.llm.client import chat_json_list, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("extract")

    lines: list[str] = []
    idx_map: dict[int, tuple[int, RawMessage]] = {}
    for seq, (orig_idx, msg) in enumerate(batch, 1):
        lines.append(f"[{seq}] 发送人: {msg.sender}\n{msg.raw_content[:500]}")
        idx_map[seq] = (orig_idx, msg)

    prompt = render_prompt("extract_batch", messages="\n\n".join(lines))
    results = chat_json_list(
        [{"role": "user", "content": prompt}],
        provider_name=provider_name,
        disable_thinking=True,
    )

    out: dict[int, list[Recommendation]] = {}
    for item in results:
        if not isinstance(item, dict) or "index" not in item:
            continue
        seq = int(item["index"])
        if seq not in idx_map:
            continue
        orig_idx, msg = idx_map[seq]
        recs: list[Recommendation] = []
        for rec_item in item.get("items", []):
            if not isinstance(rec_item, dict) or not rec_item.get("ticker"):
                continue
            recs.append(
                Recommendation(
                    message_id=msg.message_id,
                    source=msg.source,
                    sender=msg.sender,
                    message_time=msg.message_time,
                    ticker=str(rec_item.get("ticker", "")),
                    market=rec_item.get("market"),
                    action=str(rec_item.get("action", "关注")),
                    strength=str(rec_item.get("strength", "中")),
                    horizon=rec_item.get("horizon"),
                    reasoning=rec_item.get("reasoning"),
                    risk_note=rec_item.get("risk_note"),
                    raw_content=msg.raw_content,
                )
            )
        out[orig_idx] = recs
    return out


def extract(
    date_str: str,
    provider_name: str | None,
    json_output: bool,
) -> None:
    cfg = load()
    dt = parse_date(date_str)

    from stock_news.common.llm.prompts import ensure_prompts_dir
    ensure_prompts_dir()

    classified = load_classified(cfg.storage.data_dir, dt)
    if not classified:
        if json_output:
            click.echo(json.dumps({"ok": True, "data": {"date": dt.isoformat(), "recommendations": []}, "message": f"{dt} 无分类数据，请先运行 sn analyze classify"}, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{dt} 无分类数据，请先运行: sn analyze classify --date {date_str}")
        return

    rec_ids = {c.message_id for c in classified if c.category == MessageCategory.RECOMMENDATION}
    if not rec_ids:
        if json_output:
            click.echo(json.dumps({"ok": True, "data": {"date": dt.isoformat(), "recommendations": []}, "message": "无有效推荐消息"}, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{dt} 无有效推荐消息")
        return

    existing_recs = load_recommendations(cfg.storage.data_dir, dt)
    processed_ids = _load_extracted_ids(cfg.storage.data_dir, dt)

    messages = load_messages(cfg.storage.data_dir, dt)
    new_rec_messages = [m for m in messages if m.message_id in rec_ids and m.message_id not in processed_ids]

    if not new_rec_messages:
        if json_output:
            click.echo(json.dumps({
                "ok": True,
                "data": {
                    "date": dt.isoformat(),
                    "new": 0,
                    "total_recommendations": len(existing_recs),
                    "recommendations": [r.model_dump(mode="json") for r in existing_recs],
                },
                "message": f"无新推荐消息需抽取，已有 {len(existing_recs)} 条",
            }, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{dt} 无新推荐消息需抽取（已有 {len(existing_recs)} 条推荐）")
        return

    if not json_output:
        click.echo(f"  已有 {len(existing_recs)} 条推荐，新增 {len(new_rec_messages)} 条待抽取", err=True)

    indexed = list(enumerate(new_rec_messages))
    batches = [indexed[i:i + EXTRACT_BATCH_SIZE] for i in range(0, len(indexed), EXTRACT_BATCH_SIZE)]

    if not json_output:
        click.echo(f"  批量模式: {len(batches)} 批 × {EXTRACT_BATCH_SIZE} 条, 并行 {CONCURRENCY}", err=True)

    extract_map: dict[int, list[Recommendation]] = {}
    done_msgs = 0
    out_path: Path = extracted_dir(cfg.storage.data_dir, dt) / "recommendations.json"

    write_lock = threading.Lock()

    def _save_snapshot() -> None:
        with write_lock:
            _save_extracted_ids(cfg.storage.data_dir, dt, processed_ids)
            out_path.write_text(
                json.dumps([r.model_dump(mode="json") for r in existing_recs], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _fallback_one(idx: int, msg: RawMessage) -> tuple[int, list[Recommendation]]:
        try:
            return idx, _extract_by_llm(msg, provider_name)
        except Exception:
            return idx, []

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(_extract_batch_by_llm, batch, provider_name): batch for batch in batches}
        fallback_futures: dict = {}

        committed: set[int] = set()

        def _commit_indices(indices: list[int]) -> None:
            """将指定 index 的结果追加到 existing_recs 并写入磁盘."""
            new_committed = [i for i in indices if i not in committed]
            if not new_committed:
                return
            for idx in new_committed:
                recs = extract_map.get(idx, [])
                existing_recs.extend(recs)
                processed_ids.add(new_rec_messages[idx].message_id)
                committed.add(idx)
            _save_snapshot()

        for future in as_completed(futures):
            batch = futures[future]
            try:
                batch_results = future.result()
                extract_map.update(batch_results)
            except Exception as e:
                batch_results = {}
                if not json_output:
                    click.echo(f"    ⚠ 批量抽取异常: {e}", err=True)
            missed = [(idx, msg) for idx, msg in batch if idx not in extract_map]
            done_msgs += len(batch) - len(missed)
            if not json_output:
                click.echo(f"  已抽取 {done_msgs}/{len(new_rec_messages)}...", err=True)
            _commit_indices([idx for idx, _ in batch if idx in extract_map])
            if missed:
                if not json_output:
                    click.echo(f"    ↳ {len(missed)} 条缺失，提交逐条重试...", err=True)
                for idx, msg in missed:
                    fb = pool.submit(_fallback_one, idx, msg)
                    fallback_futures[fb] = (idx, msg)

        for fb_future in as_completed(fallback_futures):
            idx, recs = fb_future.result()
            extract_map[idx] = recs
            done_msgs += 1
            if not json_output:
                click.echo(f"  已抽取 {done_msgs}/{len(new_rec_messages)} (重试)...", err=True)
            _commit_indices([idx])

    new_recs: list[Recommendation] = []
    for idx in range(len(new_rec_messages)):
        new_recs.extend(extract_map.get(idx, []))

    if not json_output:
        click.echo(f"  已抽取 {len(new_rec_messages)}/{len(new_rec_messages)}...", err=True)

    all_recs = existing_recs

    if json_output:
        click.echo(json.dumps({
            "ok": True,
            "data": {
                "date": dt.isoformat(),
                "new_messages": len(new_rec_messages),
                "new_recommendations": len(new_recs),
                "total_recommendations": len(all_recs),
                "recommendations": [r.model_dump(mode="json") for r in all_recs],
            },
            "message": f"抽取完成，新增 {len(new_recs)} 条，总计 {len(all_recs)} 条推荐",
        }, ensure_ascii=False, indent=2))
    else:
        click.echo(f"\n{dt} 抽取完成: 新增 {len(new_recs)} 条，总计 {len(all_recs)} 条推荐")
        for r in new_recs:
            click.echo(f"  [{r.action}][{r.strength}] {r.ticker} - {r.sender}: {r.reasoning or ''}")
        click.echo(f"\n结果已保存: {out_path}")
