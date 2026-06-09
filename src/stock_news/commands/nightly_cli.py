"""nightly 命令注册."""

from __future__ import annotations

import json
from pathlib import Path

import click

from stock_news.commands.analyze._common import parse_date
from stock_news.common.config import load
from stock_news.common.delivery.feishu_bot import DeliveryMessage
from stock_news.common.delivery.service import (
    result_payload,
    route_targets,
    send_targets,
)
from stock_news.signals.nightly import (
    generate_nightly_report,
    nightly_paths,
    parse_datetime_expr,
    publish_nightly_html,
)


@click.group(name="nightly")
def nightly() -> None:
    """每日晚报."""


@nightly.command("generate")
@click.option("--start", "start_expr", default="yesterday-15:00", show_default=True)
@click.option("--end", "end_expr", default="today-21:00", show_default=True)
@click.option(
    "--top",
    type=click.IntRange(min=1),
    default=16,
    show_default=True,
    help="最终输出条数",
)
@click.option(
    "--candidate-top",
    type=click.IntRange(min=1),
    default=32,
    show_default=True,
    help="进入 LLM 裁判的候选条数",
)
@click.option("--with-llm", is_flag=True, help="使用 LLM 改写候选解释")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.option(
    "--html-out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="自定义 HTML 输出路径",
)
@click.option(
    "--json-out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="自定义 JSON 输出路径",
)
@click.pass_context
def nightly_generate(
    ctx: click.Context,
    start_expr: str,
    end_expr: str,
    top: int,
    candidate_top: int,
    with_llm: bool,
    provider: str | None,
    html_out: Path | None,
    json_out: Path | None,
) -> None:
    """从 recommend 数据生成晚报 JSON 和 HTML."""
    cfg = load()
    try:
        start = parse_datetime_expr(start_expr)
        end = parse_datetime_expr(end_expr)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        output = generate_nightly_report(
            cfg.storage.data_dir,
            start,
            end,
            top,
            candidate_top=candidate_top,
            use_llm=with_llm,
            provider_name=provider,
            html_out=html_out,
            json_out=json_out,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "ok": True,
        "data": {
            "window": output.payload["window"],
            "stats": output.payload["stats"],
            "json_path": str(output.json_path),
            "html_path": str(output.html_path),
        },
    }
    if ctx.obj and ctx.obj.get("json_output"):
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"晚报已生成: {output.html_path}")
    click.echo(f"结构化数据: {output.json_path}")
    click.echo(f"候选数: {output.payload['stats']['candidates']}")


@nightly.command("publish")
@click.option("--date", "date_str", default="today", show_default=True, help="晚报日期")
@click.option(
    "--html-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="自定义待发布 HTML 文件；默认读取 data/<date>/nightly/nightly.html",
)
@click.pass_context
def nightly_publish(
    ctx: click.Context,
    date_str: str,
    html_file: Path | None,
) -> None:
    """发布晚报 HTML 到配置的静态服务器."""
    cfg = load()
    dt = parse_date(date_str)
    _, default_html = nightly_paths(cfg.storage.data_dir, dt)
    local_html = html_file.expanduser() if html_file else default_html
    try:
        output = publish_nightly_html(local_html, dt, cfg.publish.nightly)
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "ok": True,
        "data": {
            "date": dt.isoformat(),
            "local_path": str(output.local_path),
            "remote_path": output.remote_path,
            "url": output.url,
        },
    }
    if ctx.obj and ctx.obj.get("json_output"):
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"晚报已发布: {output.url}")


@nightly.command("run")
@click.option("--start", "start_expr", default="yesterday-15:00", show_default=True)
@click.option("--end", "end_expr", default="today-21:00", show_default=True)
@click.option(
    "--top",
    type=click.IntRange(min=1),
    default=32,
    show_default=True,
    help="最终输出条数",
)
@click.option(
    "--candidate-top",
    type=click.IntRange(min=1),
    default=64,
    show_default=True,
    help="进入 LLM 裁判的候选条数",
)
@click.option("--provider", "-p", help="指定 LLM provider")
@click.option("--delivery-target", multiple=True, help="发送到 delivery target")
@click.option("--delivery-route", help="发送到 delivery route")
@click.pass_context
def nightly_run(
    ctx: click.Context,
    start_expr: str,
    end_expr: str,
    top: int,
    candidate_top: int,
    provider: str | None,
    delivery_target: tuple[str, ...],
    delivery_route: str | None,
) -> None:
    """生成、发布并投递每日晚报."""
    if delivery_target and delivery_route:
        raise click.ClickException("--delivery-target 和 --delivery-route 只能指定一个")

    cfg = load()
    try:
        start = parse_datetime_expr(start_expr)
        end = parse_datetime_expr(end_expr)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    report = generate_nightly_report(
        cfg.storage.data_dir,
        start,
        end,
        top,
        candidate_top=candidate_top,
        use_llm=True,
        provider_name=provider,
    )
    published = publish_nightly_html(report.html_path, end.date(), cfg.publish.nightly)

    targets: list[str] = list(delivery_target)
    fail_fast = False
    if delivery_route:
        route, targets = route_targets(delivery_route)
        fail_fast = route.fail_fast
    delivery_payload: dict[str, object] | None = None
    if targets:
        message = DeliveryMessage(
            format="markdown",
            text=_nightly_delivery_text(published.url, top),
        )
        delivery_payload = result_payload(
            send_targets(targets, message, fail_fast=fail_fast)
        )

    payload = {
        "ok": True,
        "data": {
            "window": report.payload["window"],
            "stats": report.payload["stats"],
            "json_path": str(report.json_path),
            "html_path": str(report.html_path),
            "url": published.url,
            "delivery": delivery_payload,
        },
    }
    if ctx.obj and ctx.obj.get("json_output"):
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"晚报已生成并发布: {published.url}")
    if delivery_payload:
        click.echo(str(delivery_payload["message"]))


def _nightly_delivery_text(url: str, top: int) -> str:
    return (
        f"【今晚值得重点看的 {top} 条投研逻辑】\n\n"
        "从近 30 小时的推荐信息里筛出来的强逻辑版本，"
        "优先保留有目标市值、订单客户、涨价催化和产业链位置的标的。\n\n"
        f"[点击查看今晚 Top{top} 投研逻辑]({url})"
    )
