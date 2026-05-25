"""观点链：按发送人聚合 Recommendation，调 LLM 归并 topic_key / stance."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

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
            click.echo(json.dumps({"ok": True, "data": {"date": dt.isoformat(), "opinions": []}, "message": f"{dt} 无推荐数据，请先运行 sn analyze extract"}, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{dt} 无推荐数据，请先运行: sn analyze extract --date {date_str}")
        return

    messages = load_messages(cfg.storage.data_dir, dt)
    msg_map = {m.message_id: m for m in messages}

    sender_recs: dict[str, list[Recommendation]] = {}
    for rec in recs:
        sender_recs.setdefault(rec.sender, []).append(rec)

    if not json_output:
        click.echo(f"  {len(recs)} 条推荐，{len(sender_recs)} 个发送人，按发送人并行", err=True)

    def _process_sender(sender: str, sender_rec_list: list[Recommendation]) -> list[OpinionNode]:
        history: list[str] = []
        nodes: list[OpinionNode] = []
        for rec in sender_rec_list:
            msg = msg_map.get(rec.message_id)
            if not msg:
                continue
            history_text = "\n---\n".join(history)
            try:
                node = _analyze_opinion(msg, history_text, provider_name)
                if node:
                    existing = [o for o in nodes if o.opinion_id == node.opinion_id]
                    if existing:
                        node.version = len(existing) + 1
                        node.previous_id = existing[-1].message_id
                    nodes.append(node)
            except Exception:
                pass
            history.append(f"[{rec.action}] {rec.ticker}: {msg.raw_content[:100]}")
        return nodes

    opinions: list[OpinionNode] = []
    done_count = 0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(_process_sender, sender, rec_list): sender
            for sender, rec_list in sender_recs.items()
        }
        for future in as_completed(futures):
            nodes = future.result()
            opinions.extend(nodes)
            done_count += 1
            if not json_output and done_count % 5 == 0:
                click.echo(f"  已完成 {done_count}/{len(sender_recs)} 个发送人...", err=True)

    if not json_output:
        click.echo(f"  已完成 {done_count}/{len(sender_recs)} 个发送人...", err=True)

    out_path = opinion_dir(cfg.storage.data_dir, dt) / "opinions.json"
    out_path.write_text(
        json.dumps([o.model_dump(mode="json") for o in opinions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if json_output:
        click.echo(json.dumps({
            "ok": True,
            "data": {
                "date": dt.isoformat(),
                "total": len(opinions),
                "opinions": [o.model_dump(mode="json") for o in opinions],
            },
            "message": f"观点链分析完成，共 {len(opinions)} 条",
        }, ensure_ascii=False, indent=2))
    else:
        click.echo(f"\n{dt} 观点链分析完成: {len(opinions)} 条")
        for o in opinions:
            click.echo(f"  [{o.update_type}][{o.stance}] {o.sender} -> {o.topic_key}: {o.summary}")
        click.echo(f"\n结果已保存: {out_path}")
