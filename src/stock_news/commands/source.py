"""source 命令业务适配层."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import click

from stock_news.common.config import load
from stock_news.source.models import SourceSeedResult
from stock_news.source.presentation import (
    ACTIONABLE_STATUSES,
    STATUS_ORDER,
    bucket_candidates,
    format_seed_plain,
    render_seed_markdown,
    seed_to_dict,
)
from stock_news.source.seeds import parse_as_of, scan_source_seeds
from stock_news.source.storage import radar_markdown_path
from stock_news.source.utils import parse_date

# 兼容旧测试/临时调用。
_bucket_candidates = bucket_candidates
_format_seed_plain = format_seed_plain
_render_seed_markdown = render_seed_markdown
_seed_to_dict = seed_to_dict


def _default_as_of(end: date) -> datetime:
    now = datetime.now().replace(microsecond=0)
    if end >= now.date():
        return now
    return datetime.combine(end, datetime.max.time()).replace(microsecond=0)


def _filter_seed_result(
    result: SourceSeedResult,
    *,
    include_closed: bool,
    top: int,
) -> SourceSeedResult:
    total = result.candidate_count
    if include_closed:
        source_candidates = result.candidates
    else:
        source_candidates = tuple(
            item for item in result.candidates if item.status in ACTIONABLE_STATUSES
        )
    visible_parts = []
    for status in STATUS_ORDER:
        if not include_closed and status not in ACTIONABLE_STATUSES:
            continue
        visible_parts.extend(
            list(item for item in source_candidates if item.status == status)[:top]
        )
    visible = tuple(visible_parts)
    hidden = max(total - len(visible), 0)
    return replace(
        result,
        candidates=visible,
        candidate_count=len(visible),
        total_candidate_count=total,
        hidden_count=hidden,
    )


def scan_sources(
    date_str: str,
    since_minutes: int | None,
    start_str: str | None,
    end_str: str | None,
    as_of_str: str | None,
    top: int,
    max_message_chars: int,
    include_closed: bool,
    json_output: bool,
    lookback_days: int = 30,
    write_markdown: bool = False,
    markdown_out: str | None = None,
    use_llm_brief: bool = True,
) -> None:
    """扫描本地 raw 数据中的源头种子；Markdown 落盘默认会调用 LLM 改写."""
    cfg = load()
    if since_minutes is not None and start_str is not None:
        raise click.ClickException("--since-minutes 和 --start 不能同时使用")

    window_start: datetime | None = None
    window_end: datetime | None = None
    if since_minutes is None:
        if start_str is not None:
            start = parse_date(start_str)
            end = parse_date(end_str or start_str)
        else:
            start = parse_date(date_str)
            end = start
        fallback_as_of = _default_as_of(end)
    else:
        window_end = datetime.now().replace(microsecond=0)
        window_start = window_end - timedelta(minutes=since_minutes)
        start = window_start.date()
        end = window_end.date()
        fallback_as_of = window_end
    if end < start:
        raise click.ClickException("结束日期不能早于开始日期")
    try:
        as_of_time = parse_as_of(as_of_str, fallback_as_of)
    except ValueError as exc:
        raise click.ClickException(f"非法 --as-of: {as_of_str}") from exc
    now = datetime.now().replace(microsecond=0)
    if as_of_time > now:
        raise click.ClickException(
            f"--as-of 不能晚于当前时间: {as_of_time.isoformat()} > {now.isoformat()}"
        )

    try:
        result = scan_source_seeds(
            data_dir=cfg.storage.data_dir,
            start=start,
            end=end,
            as_of_time=as_of_time,
            top=top,
            max_message_chars=max_message_chars,
            lookback_days=lookback_days,
            window_start=window_start,
            window_end=window_end,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    result = _filter_seed_result(result, include_closed=include_closed, top=top)
    md_path = _write_markdown_if_needed(
        result,
        cfg.storage.data_dir,
        end,
        write_markdown,
        markdown_out,
        use_llm_brief,
    )

    if json_output:
        click.echo(
            json.dumps(_scan_payload(result, md_path), ensure_ascii=False, indent=2)
        )
        return

    click.echo(format_seed_plain(result), nl=False)
    if md_path is not None:
        click.echo(f"Markdown 已保存: {md_path}")


def _write_markdown_if_needed(
    result: SourceSeedResult,
    data_dir: str,
    end: date,
    write_markdown: bool,
    markdown_out: str | None,
    use_llm_brief: bool,
) -> Path | None:
    if not write_markdown and not markdown_out:
        return None
    if markdown_out:
        md_path = Path(markdown_out).expanduser()
        md_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        md_path = radar_markdown_path(data_dir, end)
    md_path.write_text(
        render_seed_markdown(
            result,
            use_llm_brief=use_llm_brief,
            on_warning=lambda message: click.echo(message, err=True),
        ),
        encoding="utf-8",
    )
    return md_path


def _scan_payload(
    result: SourceSeedResult,
    md_path: Path | None,
) -> dict[str, object]:
    return {
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
            "as_of_time": result.as_of_time.isoformat(),
            "lookback_days": result.lookback_days,
            "scanned_messages": result.scanned_messages,
            "candidate_count": result.candidate_count,
            "total_candidate_count": result.total_candidate_count,
            "hidden_count": result.hidden_count,
            "markdown_path": None if md_path is None else str(md_path),
            "candidates": [seed_to_dict(item) for item in result.candidates],
            "buckets": {
                status: [seed_to_dict(item) for item in items]
                for status, items in bucket_candidates(result.candidates).items()
                if items
            },
        },
        "message": f"发现 {result.candidate_count} 个源头种子候选",
    }
