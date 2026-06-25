"""公开研究源命令注册。

这里只接线官方公开研究源的 sitemap 增量抓取和本地查询，不跑 LLM、不投递。
"""

from __future__ import annotations

import json
from dataclasses import asdict

import click

from stock_news.core.config import load
from stock_news.core.research_sources import (
    ResearchSourceFetcher,
    ResearchSyncError,
    serialize_sync_summary,
)


@click.group()
@click.pass_context
def research(ctx: click.Context) -> None:
    """公开研究源."""


@research.command("sync-ai")
@click.option("--source", "sources", multiple=True, help="只同步指定源 ID，可重复")
@click.option("--max-pages", type=int, default=None, help="本次最多抓取页面/PDF 数")
@click.option("--refresh", is_flag=True, help="忽略本地增量状态，强制重抓候选")
@click.option("--dry-run", is_flag=True, help="只发现候选 URL，不抓取正文")
@click.pass_context
def sync_ai(
    ctx: click.Context,
    sources: tuple[str, ...],
    max_pages: int | None,
    refresh: bool,
    dry_run: bool,
) -> None:
    """同步高盛/花旗/摩根大通/摩根士丹利公开 AI 研究内容。"""

    cfg = load()
    fetcher = ResearchSourceFetcher(cfg.research_sources)
    summary = fetcher.sync(
        source_ids=list(sources) or None,
        max_pages=max_pages,
        refresh=refresh,
        dry_run=dry_run,
    )
    if ctx.obj["json_output"]:
        click.echo(json.dumps(serialize_sync_summary(summary), ensure_ascii=False))
        return

    click.echo(f"研究源: {summary.sources}")
    click.echo(f"候选 URL: {summary.candidates}")
    if summary.dry_run:
        click.echo("模式: dry-run，未抓取正文")
        click.echo(f"失败: {summary.failed}")
        _print_errors(summary.errors)
        return
    click.echo(f"抓取: {summary.fetched}")
    click.echo(f"新增: {summary.inserted}")
    click.echo(f"更新: {summary.updated}")
    click.echo(f"未变: {summary.unchanged}")
    click.echo(f"跳过: {summary.skipped}")
    click.echo(f"失败: {summary.failed}")
    _print_errors(summary.errors)


@research.command("list")
@click.option("--source", default=None, help="只查看指定源 ID")
@click.option("--limit", type=int, default=20, help="最多返回条数")
@click.pass_context
def list_documents(ctx: click.Context, source: str | None, limit: int) -> None:
    """查看本地已抓取公开研究内容。"""

    cfg = load()
    fetcher = ResearchSourceFetcher(cfg.research_sources)
    rows = fetcher.list_documents(source_id=source, limit=limit)
    if ctx.obj["json_output"]:
        click.echo(json.dumps([asdict(row) for row in rows], ensure_ascii=False))
        return
    if not rows:
        click.echo("暂无研究源记录")
        return
    for row in rows:
        title = row.title or "(无标题)"
        date = row.published_at or row.sitemap_lastmod or row.fetched_at
        click.echo(f"[{row.source_name}] {date} {title}")
        click.echo(f"  {row.url}")
        if row.text_path:
            click.echo(f"  text: {row.text_path}")
        if row.binary_path:
            click.echo(f"  file: {row.binary_path}")


def _print_errors(errors: list[ResearchSyncError]) -> None:
    """输出研究源同步失败样例。"""

    if not errors:
        return
    click.secho("失败样例:", fg="yellow", err=True)
    for error in errors[:5]:
        click.secho(
            f"  [{error.source_id}] {error.url}: {error.error}",
            fg="yellow",
            err=True,
        )
