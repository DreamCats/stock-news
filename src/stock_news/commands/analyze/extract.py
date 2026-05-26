"""推荐抽取：从 RECOMMENDATION 类消息抽取结构化字段."""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
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
TARGET_TYPES = {"stock", "sector", "theme", "index", "macro", "unknown"}
MARKETS = {"A股", "港股", "美股"}
STRENGTHS = {"高", "中", "低"}
HORIZONS = {"日内", "短线", "波段", "中线"}
ACTION_ALIASES = {
    "关注": "关注",
    "推荐": "关注",
    "看好": "关注",
    "重视": "关注",
    "买入": "买入",
    "强推": "买入",
    "首推": "买入",
    "加推": "买入",
    "超配": "买入",
    "增持": "加仓",
    "加仓": "加仓",
    "减持": "减仓",
    "减仓": "减仓",
    "减配": "减仓",
    "卖出": "卖出",
    "卖点": "卖出",
    "卖了": "卖出",
    "不留": "卖出",
    "清仓": "卖出",
    "回避": "卖出",
}


def _load_extracted_ids(cfg_data_dir: str, dt: date) -> set[str]:
    path = extracted_dir(cfg_data_dir, dt) / "processed_ids.json"
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_extracted_ids(cfg_data_dir: str, dt: date, ids: set[str]) -> None:
    path = extracted_dir(cfg_data_dir, dt) / "processed_ids.json"
    path.write_text(json.dumps(sorted(ids), ensure_ascii=False), encoding="utf-8")


def _as_confidence(value: object, default: float = 0.8) -> float:
    if value is None:
        return default
    try:
        confidence = float(str(value))
    except (TypeError, ValueError):
        return default
    return min(max(confidence, 0.0), 1.0)


def _normalize_action(value: object) -> str:
    raw = str(value or "关注").strip()
    if raw in ACTION_ALIASES:
        return ACTION_ALIASES[raw]
    for key, normalized in ACTION_ALIASES.items():
        if key in raw:
            return normalized
    return "关注"


def _normalize_target_type(value: object) -> str:
    raw = str(value or "stock").strip().lower()
    return raw if raw in TARGET_TYPES else "unknown"


def _normalize_market(value: object) -> str | None:
    raw = str(value or "").strip()
    return raw if raw in MARKETS else None


def _normalize_choice(value: object, allowed: set[str], default: str) -> str:
    raw = str(value or default).strip()
    return raw if raw in allowed else default


def _recommendation_from_item(
    msg: RawMessage,
    item: dict[str, object],
) -> Recommendation | None:
    target_name = str(item.get("target_name") or item.get("ticker") or "").strip()
    if not target_name:
        return None

    raw_ticker = str(item.get("ticker") or "").strip()
    ticker = raw_ticker or target_name
    raw_action = str(item.get("raw_action") or item.get("action") or "关注").strip()
    normalized_action = _normalize_action(raw_action)
    reasoning = item.get("reasoning")
    evidence = item.get("evidence") or reasoning

    return Recommendation(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        target_type=_normalize_target_type(item.get("target_type")),
        target_name=target_name,
        ticker=ticker,
        market=_normalize_market(item.get("market")),
        raw_action=raw_action,
        normalized_action=normalized_action,
        action=normalized_action,
        strength=_normalize_choice(item.get("strength"), STRENGTHS, "中"),
        horizon=(
            str(item.get("horizon")).strip()
            if item.get("horizon") in HORIZONS
            else None
        ),
        reasoning=str(reasoning) if reasoning else None,
        risk_note=str(item.get("risk_note")) if item.get("risk_note") else None,
        confidence=_as_confidence(item.get("confidence")),
        evidence=str(evidence) if evidence else None,
        raw_content=msg.raw_content,
    )


def _extract_by_llm(msg: RawMessage, provider_name: str | None) -> list[Recommendation]:
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
        if not isinstance(item, dict):
            continue
        rec = _recommendation_from_item(msg, item)
        if rec:
            recs.append(rec)
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
        recs: list[Recommendation] = []
        raw_items = item.get("items", [])
        if not isinstance(raw_items, list):
            continue
        for rec_item in raw_items:
            if not isinstance(rec_item, dict):
                continue
            rec = _recommendation_from_item(msg, rec_item)
            if rec:
                recs.append(rec)
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
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {"date": dt.isoformat(), "recommendations": []},
                        "message": f"{dt} 无分类数据，请先运行 sn analyze classify",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(
                f"{dt} 无分类数据，请先运行: sn analyze classify --date {date_str}"
            )
        return

    rec_ids = {
        c.message_id for c in classified if c.category == MessageCategory.RECOMMENDATION
    }
    if not rec_ids:
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {"date": dt.isoformat(), "recommendations": []},
                        "message": "无有效推荐消息",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(f"{dt} 无有效推荐消息")
        return

    existing_recs = load_recommendations(cfg.storage.data_dir, dt)
    processed_ids = _load_extracted_ids(cfg.storage.data_dir, dt)

    messages = load_messages(cfg.storage.data_dir, dt)
    new_rec_messages = [
        m
        for m in messages
        if m.message_id in rec_ids and m.message_id not in processed_ids
    ]

    if not new_rec_messages:
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "date": dt.isoformat(),
                            "new": 0,
                            "total_recommendations": len(existing_recs),
                            "recommendations": [
                                r.model_dump(mode="json") for r in existing_recs
                            ],
                        },
                        "message": f"无新推荐消息需抽取，已有 {len(existing_recs)} 条",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(f"{dt} 无新推荐消息需抽取（已有 {len(existing_recs)} 条推荐）")
        return

    if not json_output:
        message = (
            f"  已有 {len(existing_recs)} 条推荐，新增 {len(new_rec_messages)} 条待抽取"
        )
        click.echo(
            message,
            err=True,
        )

    indexed = list(enumerate(new_rec_messages))
    batches = [
        indexed[i : i + EXTRACT_BATCH_SIZE]
        for i in range(0, len(indexed), EXTRACT_BATCH_SIZE)
    ]

    if not json_output:
        message = (
            f"  批量模式: {len(batches)} 批 × {EXTRACT_BATCH_SIZE} 条, "
            f"并行 {CONCURRENCY}"
        )
        click.echo(
            message,
            err=True,
        )

    extract_map: dict[int, list[Recommendation]] = {}
    done_msgs = 0
    out_path: Path = extracted_dir(cfg.storage.data_dir, dt) / "recommendations.json"

    write_lock = threading.Lock()

    def _save_snapshot() -> None:
        with write_lock:
            _save_extracted_ids(cfg.storage.data_dir, dt, processed_ids)
            out_path.write_text(
                json.dumps(
                    [r.model_dump(mode="json") for r in existing_recs],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def _fallback_one(idx: int, msg: RawMessage) -> tuple[int, list[Recommendation]]:
        try:
            return idx, _extract_by_llm(msg, provider_name)
        except Exception:
            return idx, []

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(_extract_batch_by_llm, batch, provider_name): batch
            for batch in batches
        }
        fallback_futures: dict[
            Future[tuple[int, list[Recommendation]]],
            tuple[int, RawMessage],
        ] = {}

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
                click.echo(
                    f"  已抽取 {done_msgs}/{len(new_rec_messages)} (重试)...", err=True
                )
            _commit_indices([idx])

    new_recs: list[Recommendation] = []
    for idx in range(len(new_rec_messages)):
        new_recs.extend(extract_map.get(idx, []))

    if not json_output:
        click.echo(
            f"  已抽取 {len(new_rec_messages)}/{len(new_rec_messages)}...", err=True
        )

    all_recs = existing_recs

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": dt.isoformat(),
                        "new_messages": len(new_rec_messages),
                        "new_recommendations": len(new_recs),
                        "total_recommendations": len(all_recs),
                        "recommendations": [
                            r.model_dump(mode="json") for r in all_recs
                        ],
                    },
                    "message": (
                        f"抽取完成，新增 {len(new_recs)} 条，"
                        f"总计 {len(all_recs)} 条推荐"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        click.echo(
            f"\n{dt} 抽取完成: 新增 {len(new_recs)} 条，总计 {len(all_recs)} 条推荐"
        )
        for r in new_recs:
            message = (
                f"  [{r.action}][{r.strength}] {r.ticker} - "
                f"{r.sender}: {r.reasoning or ''}"
            )
            click.echo(message)
        click.echo(f"\n结果已保存: {out_path}")
