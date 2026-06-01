"""source 命令业务适配层."""

from __future__ import annotations

import json
from datetime import date

import click

from stock_news.common.config import load
from stock_news.source.features import STRONG_TRIGGERS, evidence, snippet
from stock_news.source.models import SourceCandidate
from stock_news.source.scanner import parse_date, scan_source_candidates


def _candidate_to_dict(candidate: SourceCandidate) -> dict[str, object]:
    first = candidate.first
    first_stock = candidate.first_stock
    return {
        "term": candidate.term,
        "score": candidate.score,
        "signal_type": candidate.signal_type,
        "novelty_level": candidate.novelty_level,
        "previous_mentions": candidate.previous_mentions,
        "later_mentions": candidate.later_mentions,
        "later_days": candidate.later_days,
        "later_groups": candidate.later_groups,
        "later_senders": candidate.later_senders,
        "evidence": evidence(candidate),
        "features": {
            "message_chars": len(first.row.message.raw_content),
            "trigger_count": len(first.row.triggers),
            "has_strong_trigger": any(
                trigger in STRONG_TRIGGERS for trigger in first.row.triggers
            ),
            "has_stock_later": first_stock is not None,
            "source": first.row.message.source,
            "category": first.row.category,
        },
        "first": {
            "time": first.row.message.message_time.isoformat(),
            "group": first.row.message.group_name,
            "sender": first.row.message.sender,
            "message_id": first.row.message.message_id,
            "category": first.row.category,
            "triggers": list(first.row.triggers),
            "snippet": snippet(first.row.message.raw_content),
        },
        "first_stock": None
        if first_stock is None
        else {
            "time": first_stock.row.message.message_time.isoformat(),
            "group": first_stock.row.message.group_name,
            "sender": first_stock.row.message.sender,
            "message_id": first_stock.row.message.message_id,
            "stocks": list(first_stock.stocks[:10]),
            "snippet": snippet(first_stock.row.message.raw_content),
        },
        "stock_names": list(candidate.stock_names),
    }


def _format_plain(
    candidates: tuple[SourceCandidate, ...], start: date, end: date
) -> None:
    if not candidates:
        click.echo(f"{start} 到 {end} 未发现源头候选")
        return

    click.echo(f"{start} 到 {end} 源头候选 TOP {len(candidates)}:\n")
    for index, candidate in enumerate(candidates, start=1):
        first = candidate.first
        first_stock = candidate.first_stock
        click.echo(
            f"{index}. {candidate.term}  score={candidate.score}  "
            f"信号={candidate.signal_type}  新鲜度={candidate.novelty_level}"
        )
        click.echo(
            "   计数: "
            f"历史提及={candidate.previous_mentions}，"
            f"后续扩散={candidate.later_mentions}，"
            f"覆盖={candidate.later_days}天/"
            f"{candidate.later_groups}群/{candidate.later_senders}人"
        )
        click.echo(
            "   首次: "
            f"{first.row.message.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"{first.row.message.group_name or '-'} / {first.row.message.sender}"
        )
        click.echo(
            f"   形态: {first.row.category or '-'}，"
            f"触发={','.join(first.row.triggers)}，"
            f"message_id={first.row.message.message_id}"
        )
        candidate_evidence = "；".join(evidence(candidate))
        if candidate_evidence:
            click.echo(f"   依据: {candidate_evidence}")
        click.echo(f"   摘要: {snippet(first.row.message.raw_content)}")
        if first_stock is None:
            click.echo("   首次带股: 未发现")
        else:
            stocks = "、".join(first_stock.stocks[:8])
            click.echo(
                "   首次带股: "
                f"{first_stock.row.message.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"{first_stock.row.message.group_name or '-'} / {stocks}"
            )
        click.echo()


def scan_sources(
    start_str: str,
    end_str: str,
    lookahead_days: int,
    top: int,
    max_message_chars: int,
    json_output: bool,
) -> None:
    """扫描本地 raw 数据中的源头候选，不调用外部 API，不写文件."""
    cfg = load()
    start = parse_date(start_str)
    end = parse_date(end_str)
    if end < start:
        raise click.ClickException("结束日期不能早于开始日期")

    try:
        result = scan_source_candidates(
            data_dir=cfg.storage.data_dir,
            start=start,
            end=end,
            lookahead_days=lookahead_days,
            top=top,
            max_message_chars=max_message_chars,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "start": result.start.isoformat(),
                        "end": result.end.isoformat(),
                        "lookahead_days": result.lookahead_days,
                        "scanned_messages": result.scanned_messages,
                        "candidate_count": result.candidate_count,
                        "candidates": [
                            _candidate_to_dict(item) for item in result.candidates
                        ],
                    },
                    "message": f"发现 {result.candidate_count} 个源头候选",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _format_plain(result.candidates, result.start, result.end)
