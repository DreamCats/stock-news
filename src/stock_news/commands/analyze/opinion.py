"""观点链：按发送人聚合 Recommendation，调 LLM 归并 topic_key / stance."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import click

from stock_news.commands.analyze._common import (
    load_recommendations,
    opinion_dir,
    parse_date,
)
from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import OpinionNode, RawMessage, Recommendation

CONCURRENCY = 8


def _opinions_path(cfg_data_dir: str, dt: date) -> Path:
    return opinion_dir(cfg_data_dir, dt) / "opinions.json"


def _processed_ids_path(cfg_data_dir: str, dt: date) -> Path:
    return opinion_dir(cfg_data_dir, dt) / "processed_ids.json"


def _load_opinions(cfg_data_dir: str, dt: date) -> list[OpinionNode]:
    path = _opinions_path(cfg_data_dir, dt)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [OpinionNode.model_validate(item) for item in data]


def _load_processed_ids(
    cfg_data_dir: str,
    dt: date,
    opinions: list[OpinionNode],
) -> set[str]:
    path = _processed_ids_path(cfg_data_dir, dt)
    if not path.exists():
        return {o.message_id for o in opinions}
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_opinion_state(
    cfg_data_dir: str,
    dt: date,
    opinions: list[OpinionNode],
    processed_ids: set[str],
) -> None:
    opinions_path = _opinions_path(cfg_data_dir, dt)
    data = [o.model_dump(mode="json") for o in opinions]
    opinions_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _processed_ids_path(cfg_data_dir, dt).write_text(
        json.dumps(sorted(processed_ids), ensure_ascii=False),
        encoding="utf-8",
    )


def _history_from_opinions(opinions: list[OpinionNode]) -> list[str]:
    return [
        f"[{o.update_type}][{o.stance}] {o.topic_key}: {o.summary}"
        for o in opinions
    ]


def _analyze_opinion(
    msg: RawMessage,
    history_text: str,
    provider_name: str | None,
) -> OpinionNode | None:
    from stock_news.common.llm.client import chat_json, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("opinion")

    prompt = render_prompt(
        "opinion",
        sender=msg.sender,
        raw_content=msg.raw_content,
        history=history_text or "(无历史观点)",
    )
    result = chat_json(
        [{"role": "user", "content": prompt}],
        provider_name=provider_name,
    )

    topic_key = str(result.get("topic_key", ""))
    if not topic_key:
        return None

    oid = hashlib.sha256(f"{msg.sender}|{topic_key}".encode()).hexdigest()[:12]

    return OpinionNode(
        opinion_id=oid,
        version=1,
        message_id=msg.message_id,
        sender=msg.sender,
        topic_key=topic_key,
        stance=str(result.get("stance", "neutral")),
        update_type=str(result.get("update_type", "new")),
        summary=str(result.get("summary", "")),
    )


def opinion(
    date_str: str,
    provider_name: str | None,
    json_output: bool,
) -> None:
    cfg = load()
    dt = parse_date(date_str)

    from stock_news.common.llm.prompts import ensure_prompts_dir
    ensure_prompts_dir()

    recs = load_recommendations(cfg.storage.data_dir, dt)
    if not recs:
        if json_output:
            click.echo(json.dumps({
                "ok": True,
                "data": {"date": dt.isoformat(), "opinions": []},
                "message": f"{dt} 无推荐数据，请先运行 sn analyze extract",
            }, ensure_ascii=False, indent=2))
        else:
            click.echo(
                f"{dt} 无推荐数据，请先运行: "
                f"sn analyze extract --date {date_str}"
            )
        return

    existing_opinions = _load_opinions(cfg.storage.data_dir, dt)
    processed_ids = _load_processed_ids(cfg.storage.data_dir, dt, existing_opinions)
    new_recs = [rec for rec in recs if rec.message_id not in processed_ids]

    if not new_recs:
        if json_output:
            click.echo(json.dumps({
                "ok": True,
                "data": {
                    "date": dt.isoformat(),
                    "new": 0,
                    "total": len(existing_opinions),
                    "opinions": [o.model_dump(mode="json") for o in existing_opinions],
                },
                "message": f"无新推荐需归并观点，已有 {len(existing_opinions)} 条观点",
            }, ensure_ascii=False, indent=2))
        else:
            click.echo(
                f"{dt} 无新推荐需归并观点"
                f"（已有 {len(existing_opinions)} 条观点）"
            )
        return

    messages = load_messages(cfg.storage.data_dir, dt)
    msg_map = {m.message_id: m for m in messages}

    sender_recs: dict[str, list[Recommendation]] = {}
    for rec in new_recs:
        sender_recs.setdefault(rec.sender, []).append(rec)

    opinions_by_sender: dict[str, list[OpinionNode]] = {}
    for node in existing_opinions:
        opinions_by_sender.setdefault(node.sender, []).append(node)

    if not json_output:
        click.echo(
            f"  已有 {len(existing_opinions)} 条观点，新增 {len(new_recs)} 条推荐，"
            f"{len(sender_recs)} 个发送人，按发送人并行",
            err=True,
        )

    def _process_sender(
        sender: str,
        sender_rec_list: list[Recommendation],
    ) -> tuple[list[OpinionNode], set[str], int]:
        history = _history_from_opinions(opinions_by_sender.get(sender, []))
        nodes: list[OpinionNode] = []
        done_ids: set[str] = set()
        failed = 0
        for rec in sender_rec_list:
            msg = msg_map.get(rec.message_id)
            if not msg:
                failed += 1
                continue
            history_text = "\n---\n".join(history)
            try:
                node = _analyze_opinion(msg, history_text, provider_name)
                if node:
                    same_topic = [
                        o
                        for o in opinions_by_sender.get(sender, []) + nodes
                        if o.opinion_id == node.opinion_id
                    ]
                    if same_topic:
                        node.version = len(same_topic) + 1
                        node.previous_id = same_topic[-1].message_id
                    nodes.append(node)
                    history.append(
                        f"[{node.update_type}][{node.stance}] "
                        f"{node.topic_key}: {node.summary}"
                    )
                done_ids.add(rec.message_id)
            except Exception:
                failed += 1
        return nodes, done_ids, failed

    opinions = list(existing_opinions)
    done_count = 0
    new_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(_process_sender, sender, rec_list): sender
            for sender, rec_list in sender_recs.items()
        }
        for future in as_completed(futures):
            nodes, done_ids, failed = future.result()
            opinions.extend(nodes)
            processed_ids.update(done_ids)
            failed_count += failed
            new_count += len(nodes)
            done_count += 1
            _save_opinion_state(cfg.storage.data_dir, dt, opinions, processed_ids)
            if not json_output and done_count % 5 == 0:
                click.echo(
                    f"  已完成 {done_count}/{len(sender_recs)} 个发送人...",
                    err=True,
                )

    if not json_output:
        click.echo(f"  已完成 {done_count}/{len(sender_recs)} 个发送人...", err=True)

    _save_opinion_state(cfg.storage.data_dir, dt, opinions, processed_ids)

    if json_output:
        click.echo(json.dumps({
            "ok": True,
            "data": {
                "date": dt.isoformat(),
                "new": new_count,
                "total": len(opinions),
                "failed": failed_count,
                "opinions": [o.model_dump(mode="json") for o in opinions],
            },
            "message": f"观点链分析完成，新增 {new_count} 条，总计 {len(opinions)} 条",
        }, ensure_ascii=False, indent=2))
    else:
        click.echo(
            f"\n{dt} 观点链分析完成: "
            f"新增 {new_count} 条，总计 {len(opinions)} 条"
        )
        if failed_count:
            click.echo(f"  {failed_count} 条处理失败，下次会自动重试")
        new_opinions = opinions[-new_count:] if new_count else []
        for o in new_opinions:
            click.echo(
                f"  [{o.update_type}][{o.stance}] "
                f"{o.sender} -> {o.topic_key}: {o.summary}"
            )
        click.echo(f"\n结果已保存: {_opinions_path(cfg.storage.data_dir, dt)}")
