"""观点链：按发送人聚合 Recommendation，调 LLM 归并 topic_key / stance."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from difflib import SequenceMatcher
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
OPINION_BATCH_SIZE = 16
OPINION_HISTORY_LIMIT = 80
OPINION_MESSAGE_CHAR_LIMIT = 1500
OPINION_REVIEW_CONFIDENCE_THRESHOLD = 0.75
OPINION_RISK_UPDATE_TYPES = {"revise", "reverse", "withdraw"}


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
    opinion_ids = {o.message_id for o in opinions}
    path = _processed_ids_path(cfg_data_dir, dt)
    if not path.exists():
        return opinion_ids
    return set(json.loads(path.read_text(encoding="utf-8"))) | opinion_ids


def _dedupe_recommendations_by_message(
    recs: list[Recommendation],
) -> list[Recommendation]:
    seen: set[str] = set()
    unique: list[Recommendation] = []
    for rec in recs:
        if rec.message_id in seen:
            continue
        seen.add(rec.message_id)
        unique.append(rec)
    return unique


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
        f"[{o.update_type}][{o.stance}] {o.topic_key}: {o.summary}" for o in opinions
    ][-OPINION_HISTORY_LIMIT:]


def _chunked(
    items: list[Recommendation],
    size: int,
) -> list[list[Recommendation]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _opinion_node_from_result(
    msg: RawMessage,
    result: dict[str, object],
) -> OpinionNode | None:
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
        confidence=_as_confidence(result.get("confidence")),
        candidate_existing_topic=_optional_str(result.get("candidate_existing_topic")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_confidence(value: object, default: float = 0.8) -> float:
    if value is None:
        return default
    try:
        confidence = float(str(value))
    except (TypeError, ValueError):
        return default
    return min(max(confidence, 0.0), 1.0)


def _similar_topic(a: str, b: str) -> bool:
    if not a or not b or a == b:
        return False
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.82


def _needs_slow_review(node: OpinionNode, history: list[OpinionNode]) -> bool:
    if node.confidence < OPINION_REVIEW_CONFIDENCE_THRESHOLD:
        return True
    if node.update_type in OPINION_RISK_UPDATE_TYPES:
        return True

    history_topics = {item.topic_key for item in history}
    if (
        node.candidate_existing_topic
        and node.candidate_existing_topic in history_topics
        and node.candidate_existing_topic != node.topic_key
    ):
        return True

    if node.update_type == "new":
        return any(_similar_topic(node.topic_key, topic) for topic in history_topics)

    return False


def _analyze_opinion(
    msg: RawMessage,
    history_text: str,
    provider_name: str | None,
) -> OpinionNode | None:
    from stock_news.common.llm.client import chat_json, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("opinion")

    messages = render_prompt_messages(
        "opinion",
        sender=msg.sender,
        raw_content=msg.raw_content,
        history=history_text or "(无历史观点)",
    )
    result = chat_json(
        messages,
        provider_name=provider_name,
        disable_thinking=True,
    )

    topic_key = str(result.get("topic_key", ""))
    if not topic_key:
        return None

    return _opinion_node_from_result(msg, result)


def _review_opinion(
    msg: RawMessage,
    history_text: str,
    provider_name: str | None,
) -> OpinionNode | None:
    from stock_news.common.llm.client import chat_json, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("opinion")

    messages = render_prompt_messages(
        "opinion",
        sender=msg.sender,
        raw_content=msg.raw_content,
        history=history_text or "(无历史观点)",
    )
    result = chat_json(
        messages,
        provider_name=provider_name,
        disable_thinking=False,
    )

    topic_key = str(result.get("topic_key", ""))
    if not topic_key:
        return None

    return _opinion_node_from_result(msg, result)


def _analyze_opinion_batch(
    sender: str,
    msgs: list[RawMessage],
    history_text: str,
    provider_name: str | None,
) -> dict[int, OpinionNode | None]:
    from stock_news.common.llm.client import chat_json_list, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("opinion")

    lines: list[str] = []
    msg_map: dict[int, RawMessage] = {}
    for seq, msg in enumerate(msgs, 1):
        content = msg.raw_content[:OPINION_MESSAGE_CHAR_LIMIT]
        lines.append(f"[{seq}]\n{content}")
        msg_map[seq] = msg

    messages = render_prompt_messages(
        "opinion_batch",
        sender=sender,
        history=history_text or "(无历史观点)",
        messages="\n\n".join(lines),
    )
    results = chat_json_list(
        messages,
        provider_name=provider_name,
        disable_thinking=True,
    )

    out: dict[int, OpinionNode | None] = {}
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
        if seq not in msg_map:
            continue
        out[seq - 1] = _opinion_node_from_result(msg_map[seq], item)
    return out


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
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {"date": dt.isoformat(), "opinions": []},
                        "message": f"{dt} 无推荐数据，请先运行 sn analyze extract",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(
                f"{dt} 无推荐数据，请先运行: sn analyze extract --date {date_str}"
            )
        return

    existing_opinions = _load_opinions(cfg.storage.data_dir, dt)
    processed_ids = _load_processed_ids(cfg.storage.data_dir, dt, existing_opinions)
    new_rec_rows = [rec for rec in recs if rec.message_id not in processed_ids]
    new_recs = _dedupe_recommendations_by_message(new_rec_rows)

    if not new_recs:
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "date": dt.isoformat(),
                            "new": 0,
                            "total": len(existing_opinions),
                            "opinions": [
                                o.model_dump(mode="json") for o in existing_opinions
                            ],
                        },
                        "message": (
                            f"无新推荐需归并观点，已有 {len(existing_opinions)} 条观点"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(
                f"{dt} 无新推荐需归并观点（已有 {len(existing_opinions)} 条观点）"
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
            f"  已有 {len(existing_opinions)} 条观点，"
            f"新增 {len(new_rec_rows)} 条推荐（{len(new_recs)} 条消息），"
            f"{len(sender_recs)} 个发送人，按发送人分批并行",
            err=True,
        )

    def _process_sender(
        sender: str,
        sender_rec_list: list[Recommendation],
    ) -> tuple[list[OpinionNode], set[str], int, int]:
        history = _history_from_opinions(opinions_by_sender.get(sender, []))
        nodes: list[OpinionNode] = []
        done_ids: set[str] = set()
        failed = 0
        reviewed = 0

        def _append_node(node: OpinionNode | None) -> None:
            if not node:
                return
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
                f"[{node.update_type}][{node.stance}] {node.topic_key}: {node.summary}"
            )
            if len(history) > OPINION_HISTORY_LIMIT:
                del history[:-OPINION_HISTORY_LIMIT]

        def _maybe_review(
            node: OpinionNode | None, msg: RawMessage
        ) -> OpinionNode | None:
            nonlocal reviewed
            if not node:
                return None
            sender_history = opinions_by_sender.get(sender, []) + nodes
            if not _needs_slow_review(node, sender_history):
                return node
            reviewed += 1
            try:
                reviewed_node = _review_opinion(
                    msg,
                    "\n---\n".join(history),
                    provider_name,
                )
            except Exception:
                return node
            return reviewed_node or node

        def _fallback_one(msg: RawMessage) -> bool:
            try:
                node = _maybe_review(
                    _analyze_opinion(msg, history_text, provider_name),
                    msg,
                )
                _append_node(node)
                done_ids.add(msg.message_id)
                return True
            except Exception:
                return False

        for batch in _chunked(sender_rec_list, OPINION_BATCH_SIZE):
            batch_msgs: list[RawMessage] = []
            for rec in batch:
                msg = msg_map.get(rec.message_id)
                if not msg:
                    failed += 1
                    continue
                batch_msgs.append(msg)

            if not batch_msgs:
                continue

            history_text = "\n---\n".join(history)
            if len(batch_msgs) == 1:
                if not _fallback_one(batch_msgs[0]):
                    failed += 1
                continue

            try:
                batch_nodes = _analyze_opinion_batch(
                    sender,
                    batch_msgs,
                    history_text,
                    provider_name,
                )
            except Exception:
                batch_nodes = {}

            for idx, msg in enumerate(batch_msgs):
                if idx in batch_nodes:
                    _append_node(_maybe_review(batch_nodes[idx], msg))
                    done_ids.add(msg.message_id)
                    continue

                history_text = "\n---\n".join(history)
                if not _fallback_one(msg):
                    failed += 1
        return nodes, done_ids, failed, reviewed

    opinions = list(existing_opinions)
    done_count = 0
    new_count = 0
    failed_count = 0
    review_count = 0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(_process_sender, sender, rec_list): sender
            for sender, rec_list in sender_recs.items()
        }
        for future in as_completed(futures):
            nodes, done_ids, failed, reviewed = future.result()
            opinions.extend(nodes)
            processed_ids.update(done_ids)
            failed_count += failed
            review_count += reviewed
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
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": dt.isoformat(),
                        "new": new_count,
                        "total": len(opinions),
                        "failed": failed_count,
                        "reviewed": review_count,
                        "opinions": [o.model_dump(mode="json") for o in opinions],
                    },
                    "message": (
                        f"观点链分析完成，新增 {new_count} 条，总计 {len(opinions)} 条"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        click.echo(
            f"\n{dt} 观点链分析完成: 新增 {new_count} 条，总计 {len(opinions)} 条"
        )
        if failed_count:
            click.echo(f"  {failed_count} 条处理失败，下次会自动重试")
        if review_count:
            click.echo(f"  慢速复核 {review_count} 条")
        new_opinions = opinions[-new_count:] if new_count else []
        for o in new_opinions:
            click.echo(
                f"  [{o.update_type}][{o.stance}] "
                f"{o.sender} -> {o.topic_key}: {o.summary}"
            )
        click.echo(f"\n结果已保存: {_opinions_path(cfg.storage.data_dir, dt)}")
