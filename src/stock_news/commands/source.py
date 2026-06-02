"""source 命令业务适配层."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import click

from stock_news.common.config import load
from stock_news.source.features import STRONG_TRIGGERS, evidence, snippet
from stock_news.source.models import SourceCandidate, SourceScanResult
from stock_news.source.scanner import parse_date, scan_source_candidates
from stock_news.source.storage import radar_markdown_path


def _candidate_to_dict(candidate: SourceCandidate) -> dict[str, object]:
    first = candidate.first
    first_stock = candidate.first_stock
    return {
        "term": candidate.term,
        "score": candidate.score,
        "signal_type": candidate.signal_type,
        "novelty_level": candidate.novelty_level,
        "previous_mentions": candidate.previous_mentions,
        "baseline_daily": candidate.baseline_daily,
        "surge_count": candidate.surge_count,
        "surge_groups": candidate.surge_groups,
        "surge_ratio": candidate.surge_ratio,
        "aliases": list(candidate.aliases),
        "t3_groups": candidate.t3_groups,
        "t3_senders": candidate.t3_senders,
        "t3_stocks": list(candidate.t3_stocks),
        "verified": candidate.verified,
        "verdict": candidate.verdict,
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


def _window_label(result: SourceScanResult) -> str:
    if result.window_start is not None and result.window_end is not None:
        start = result.window_start.strftime("%Y-%m-%d %H:%M:%S")
        end = result.window_end.strftime("%Y-%m-%d %H:%M:%S")
        return f"{start} 到 {end}"
    return f"{result.start} 到 {result.end}"


def _format_plain(result: SourceScanResult) -> None:
    candidates = result.candidates
    label = _window_label(result)
    if not candidates:
        click.echo(f"{label} 未发现源头候选")
        return

    click.echo(f"{label} 源头候选 TOP {len(candidates)}:\n")
    for index, candidate in enumerate(candidates, start=1):
        first = candidate.first
        first_stock = candidate.first_stock
        mark = "✓真" if candidate.verified else ""
        click.echo(
            f"{index}. {candidate.term}  score={candidate.score}  "
            f"信号={candidate.signal_type}  新鲜度={candidate.novelty_level}"
            + (f"  {mark}" if mark else "")
        )
        if candidate.aliases:
            click.echo("   同源词: " + "、".join(candidate.aliases))
        click.echo(
            "   计数: "
            f"历史基线={candidate.baseline_daily}/天，"
            f"当日放量={candidate.surge_count}次/{candidate.surge_groups}群"
            f"（{candidate.surge_ratio}×），"
            f"后续扩散={candidate.later_mentions}次/"
            f"{candidate.later_days}天/{candidate.later_groups}群"
        )
        t3_stocks = (
            "，落地个股=" + "、".join(candidate.t3_stocks[:6])
            if candidate.t3_stocks
            else ""
        )
        click.echo(
            f"   T+{result.lookahead_days}: "
            f"接力={candidate.t3_senders}人/{candidate.t3_groups}群"
            f"{t3_stocks} → {candidate.verdict}"
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


def _render_markdown(result: SourceScanResult) -> str:
    """把扫描榜单渲染成一篇 Markdown 文档（可直接 delivery --markdown-file 推送）。"""
    label = _window_label(result)
    lines: list[str] = [
        f"# 源头雷达 · {label}",
        "",
        f"- 扫描消息数：{result.scanned_messages}",
        f"- 源头候选数：{result.candidate_count}",
        f"- 观察窗口：T+{result.lookahead_days} 天",
        "",
    ]

    candidates = result.candidates
    if not candidates:
        lines.append("> 本窗口未发现源头候选。")
        return "\n".join(lines) + "\n"

    lines += [
        f"## TOP {len(candidates)} 榜单",
        "",
        f"| # | 词 | 信号 | 倍率 | 基线/天 | 当日放量 | "
        f"T+{result.lookahead_days}接力 | 落地个股 | 裁决 |",
        "|--:|----|------|-----:|-----:|------|------|------|------|",
    ]
    for index, candidate in enumerate(candidates, start=1):
        mark = " ✓真" if candidate.verified else ""
        stocks = "、".join(candidate.t3_stocks[:4]) if candidate.t3_stocks else "—"
        lines.append(
            f"| {index} | {candidate.term}{mark} | {candidate.signal_type} | "
            f"{candidate.surge_ratio}× | {candidate.baseline_daily} | "
            f"{candidate.surge_count}次/{candidate.surge_groups}群 | "
            f"{candidate.t3_senders}人/{candidate.t3_groups}群 | "
            f"{stocks} | {candidate.verdict or '—'} |"
        )
    lines.append("")

    lines += ["## 候选明细", ""]
    for index, candidate in enumerate(candidates, start=1):
        first = candidate.first
        mark = " ✓真" if candidate.verified else ""
        lines.append(
            f"### {index}. {candidate.term}{mark}"
            f"（{candidate.signal_type} / 新鲜度 {candidate.novelty_level}）"
        )
        if candidate.aliases:
            lines.append(f"- 同源词：{'、'.join(candidate.aliases)}")
        lines.append(
            f"- 计数：历史基线 {candidate.baseline_daily}/天，"
            f"当日放量 {candidate.surge_count}次/{candidate.surge_groups}群"
            f"（{candidate.surge_ratio}×），"
            f"后续扩散 {candidate.later_mentions}次/{candidate.later_days}天/"
            f"{candidate.later_groups}群"
        )
        t3_stocks = (
            "，落地个股 " + "、".join(candidate.t3_stocks[:6])
            if candidate.t3_stocks
            else ""
        )
        lines.append(
            f"- T+{result.lookahead_days}：接力 "
            f"{candidate.t3_senders}人/{candidate.t3_groups}群"
            f"{t3_stocks} → {candidate.verdict or '—'}"
        )
        lines.append(
            f"- 首现：{first.row.message.message_time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"{first.row.message.group_name or '-'} / {first.row.message.sender}"
        )
        candidate_evidence = "；".join(evidence(candidate))
        if candidate_evidence:
            lines.append(f"- 依据：{candidate_evidence}")
        lines.append(f"- 摘要：{snippet(first.row.message.raw_content)}")
        lines.append("")

    return "\n".join(lines) + "\n"


def scan_sources(
    since_minutes: int | None,
    start_str: str | None,
    end_str: str,
    lookahead_days: int,
    top: int,
    max_message_chars: int,
    json_output: bool,
    lookback_days: int = 30,
    write_markdown: bool = False,
    markdown_out: str | None = None,
) -> None:
    """扫描本地 raw 数据中的源头候选，不调用外部 API.

    write_markdown / markdown_out 为真时，把榜单额外渲染成 Markdown 落盘
    （默认 data/<end>/source_scan/radar.md），供 sn delivery send --markdown-file 推送。
    """
    cfg = load()
    if since_minutes is not None and start_str is not None:
        raise click.ClickException("--since-minutes 和 --start 不能同时使用")
    if since_minutes is None and start_str is None:
        raise click.ClickException("请指定 --since-minutes 或 --start")

    window_start: datetime | None = None
    window_end: datetime | None = None
    if since_minutes is None:
        assert start_str is not None
        start = parse_date(start_str)
        end = parse_date(end_str)
    else:
        window_end = datetime.now().replace(microsecond=0)
        window_start = window_end - timedelta(minutes=since_minutes)
        start = window_start.date()
        end = window_end.date()
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
            lookback_days=lookback_days,
            window_start=window_start,
            window_end=window_end,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    md_path: Path | None = None
    if write_markdown or markdown_out:
        if markdown_out:
            md_path = Path(markdown_out).expanduser()
            md_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            md_path = radar_markdown_path(cfg.storage.data_dir, end)
        md_path.write_text(_render_markdown(result), encoding="utf-8")

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "start": result.start.isoformat(),
                        "end": result.end.isoformat(),
                        "window_start": None
                        if result.window_start is None
                        else result.window_start.isoformat(),
                        "window_end": None
                        if result.window_end is None
                        else result.window_end.isoformat(),
                        "lookahead_days": result.lookahead_days,
                        "scanned_messages": result.scanned_messages,
                        "candidate_count": result.candidate_count,
                        "markdown_path": None if md_path is None else str(md_path),
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
        _format_plain(result)
        if md_path is not None:
            click.echo(f"Markdown 已保存: {md_path}")
