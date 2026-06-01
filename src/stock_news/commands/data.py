"""本地数据查询命令."""

from __future__ import annotations

import json
from datetime import date

import click

from stock_news.common.config import load
from stock_news.common.storage import (
    dedup_date,
    find_duplicates,
    get_stats,
    load_messages,
)


def _parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        from datetime import timedelta

        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def stats(date_str: str, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)
    data = get_stats(cfg.storage.data_dir, dt)

    if json_output:
        click.echo(
            json.dumps(
                {"ok": True, "data": data, "message": f"{dt} 数据统计"},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        click.echo(f"日期: {data['date']}")
        click.echo(f"消息总数: {data['total']}")
        sources = data.get("sources", {})
        if sources:
            assert isinstance(sources, dict)
            click.echo("来源分布:")
            for src, cnt in sources.items():
                click.echo(f"  {src}: {cnt} 条")
        click.echo(f"发送人数: {data.get('senders_count', 0)}")
        top = data.get("top_senders", {})
        if top:
            assert isinstance(top, dict)
            click.echo("活跃发送人 (TOP 10):")
            for sender, cnt in top.items():
                click.echo(f"  {sender}: {cnt} 条")
        time_range = data.get("time_range")
        if time_range:
            assert isinstance(time_range, dict)
            click.echo(f"时间范围: {time_range['start']} -> {time_range['end']}")


def list_messages(date_str: str, source: str | None, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)
    messages = load_messages(cfg.storage.data_dir, dt, source)

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": dt.isoformat(),
                        "count": len(messages),
                        "messages": [m.model_dump(mode="json") for m in messages],
                    },
                    "message": f"{dt} 共 {len(messages)} 条消息",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if not messages:
            click.echo(f"{dt} 无消息")
            return
        click.echo(f"{dt} 共 {len(messages)} 条消息:\n")
        for m in messages:
            prefix = f"[{m.source}]"
            if m.group_name:
                prefix += f"[{m.group_name}]"
            time_str = m.message_time.strftime("%H:%M:%S")
            content = m.raw_content[:80]
            if len(m.raw_content) > 80:
                content += "..."
            click.echo(f"  {time_str} {prefix} {m.sender}: {content}")


def dedup(date_str: str, dry_run: bool, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)

    if dry_run:
        dups = find_duplicates(cfg.storage.data_dir, dt)
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {"date": dt.isoformat(), "duplicates": dups},
                        "message": f"发现 {len(dups)} 条重复",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if not dups:
                click.echo(f"{dt} 无重复消息")
            else:
                click.echo(f"{dt} 发现 {len(dups)} 条重复:")
                for d in dups[:20]:
                    click.echo(
                        f"  {d['sender']} {d['time']} "
                        f"(首次: {d['first_file']}, 重复: {d['dup_file']})"
                    )
    else:
        removed = dedup_date(cfg.storage.data_dir, dt)
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": True,
                        "data": {"date": dt.isoformat(), "removed": removed},
                        "message": f"已删除 {removed} 条重复",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(f"{dt} 已删除 {removed} 条重复消息")
