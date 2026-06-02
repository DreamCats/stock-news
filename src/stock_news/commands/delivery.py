"""消息投递命令."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import click

from stock_news.common.config import load, save
from stock_news.common.delivery.feishu_bot import (
    DeliveryMessage,
    resolve_user_by_email,
)
from stock_news.common.delivery.service import (
    ensure_provider_exists,
    providers_data,
    result_payload,
    route_targets,
    routes_data,
    send_file_targets,
    send_targets,
    targets_data,
)
from stock_news.models import (
    DeliveryProviderConfig,
    DeliveryRouteConfig,
    DeliveryTargetConfig,
)

MessageFormat = Literal["text", "post", "markdown", "markdown_v2"]


def _json_output(ctx: click.Context) -> bool:
    return bool(ctx.obj and ctx.obj.get("json_output"))


def _echo_json(payload: dict[str, object]) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@click.group(name="delivery")
def delivery() -> None:
    """任务结果投递."""


@delivery.group(name="provider")
def provider_group() -> None:
    """投递 provider 管理."""


@provider_group.command("add-feishu")
@click.argument("name")
@click.option("--app-id", required=True, help="飞书应用 app_id")
@click.option("--app-secret", required=True, help="飞书应用 app_secret")
@click.option("--base-url", default="https://open.feishu.cn", show_default=True)
@click.option("--timeout", type=int, default=30, show_default=True)
@click.pass_context
def provider_add_feishu(
    ctx: click.Context,
    name: str,
    app_id: str,
    app_secret: str,
    base_url: str,
    timeout: int,
) -> None:
    """添加飞书应用机器人 provider."""
    cfg = load()
    cfg.delivery.providers[name] = DeliveryProviderConfig(
        type="feishu_bot",
        app_id=app_id,
        app_secret=app_secret,
        base_url=base_url,
        timeout=timeout,
    )
    save(cfg)
    if _json_output(ctx):
        _echo_json({"ok": True, "provider": name, "message": "provider 已保存"})
    else:
        click.echo(f"provider 已保存: {name}")


@provider_group.command("add-wecom")
@click.argument("name")
@click.option("--webhook-url", required=True, help="企业微信群机器人 webhook URL")
@click.option("--timeout", type=int, default=30, show_default=True)
@click.pass_context
def provider_add_wecom(
    ctx: click.Context,
    name: str,
    webhook_url: str,
    timeout: int,
) -> None:
    """添加企业微信群机器人 provider."""
    cfg = load()
    cfg.delivery.providers[name] = DeliveryProviderConfig(
        type="wecom_bot",
        webhook_url=webhook_url,
        timeout=timeout,
    )
    save(cfg)
    if _json_output(ctx):
        _echo_json({"ok": True, "provider": name, "message": "provider 已保存"})
    else:
        click.echo(f"provider 已保存: {name}")


@provider_group.command("list")
@click.pass_context
def provider_list(ctx: click.Context) -> None:
    """列出 delivery providers."""
    data = providers_data()
    if _json_output(ctx):
        _echo_json({"ok": True, "data": data})
        return
    if not data:
        click.echo("未配置 delivery provider")
        return
    for name, p in data.items():
        if p["type"] == "feishu_bot":
            click.echo(f"{name}: {p['type']} app_id={p['app_id']}")
        else:
            click.echo(f"{name}: {p['type']} webhook={p['webhook_url']}")


@delivery.group(name="target")
def target_group() -> None:
    """投递 target 管理."""


@target_group.command("add-user")
@click.argument("name")
@click.option(
    "--provider", "provider_name", required=True, help="delivery provider 名称"
)
@click.option("--email", help="飞书用户邮箱，用于解析 open_id")
@click.option("--open-id", "open_id", help="飞书 open_id（ou_xxx）")
@click.option("--display-name", help="备注名")
@click.pass_context
def target_add_user(
    ctx: click.Context,
    name: str,
    provider_name: str,
    email: str | None,
    open_id: str | None,
    display_name: str | None,
) -> None:
    """添加单个用户 target."""
    if not email and not open_id:
        raise click.ClickException("--email 和 --open-id 至少指定一个")
    ensure_provider_exists(provider_name)
    cfg = load()
    cfg.delivery.targets[name] = DeliveryTargetConfig(
        provider=provider_name,
        kind="user",
        id=open_id,
        email=email,
        name=display_name,
        resolved_id=open_id,
    )
    save(cfg)
    if _json_output(ctx):
        _echo_json({"ok": True, "target": name, "message": "user target 已保存"})
    else:
        click.echo(f"user target 已保存: {name}")


@target_group.command("add-chat")
@click.argument("name")
@click.option(
    "--provider", "provider_name", required=True, help="delivery provider 名称"
)
@click.option("--chat-id", required=True, help="飞书群聊 chat_id（oc_xxx）")
@click.pass_context
def target_add_chat(
    ctx: click.Context,
    name: str,
    provider_name: str,
    chat_id: str,
) -> None:
    """添加单个群聊 target."""
    ensure_provider_exists(provider_name)
    cfg = load()
    cfg.delivery.targets[name] = DeliveryTargetConfig(
        provider=provider_name,
        kind="chat",
        id=chat_id,
        resolved_id=chat_id,
    )
    save(cfg)
    if _json_output(ctx):
        _echo_json({"ok": True, "target": name, "message": "chat target 已保存"})
    else:
        click.echo(f"chat target 已保存: {name}")


@target_group.command("add-webhook")
@click.argument("name")
@click.option(
    "--provider", "provider_name", required=True, help="delivery provider 名称"
)
@click.option("--display-name", help="备注名")
@click.pass_context
def target_add_webhook(
    ctx: click.Context,
    name: str,
    provider_name: str,
    display_name: str | None,
) -> None:
    """添加 webhook target（如企业微信群机器人）."""
    ensure_provider_exists(provider_name)
    cfg = load()
    provider = cfg.delivery.providers[provider_name]
    if provider.type != "wecom_bot":
        raise click.ClickException("add-webhook 仅支持 wecom_bot provider")
    cfg.delivery.targets[name] = DeliveryTargetConfig(
        provider=provider_name,
        kind="webhook",
        name=display_name,
        resolved_id=name,
    )
    save(cfg)
    if _json_output(ctx):
        _echo_json({"ok": True, "target": name, "message": "webhook target 已保存"})
    else:
        click.echo(f"webhook target 已保存: {name}")


@target_group.command("resolve")
@click.argument("name")
@click.pass_context
def target_resolve(ctx: click.Context, name: str) -> None:
    """解析 target 的 provider-specific ID."""
    cfg = load()
    target = cfg.delivery.targets.get(name)
    if target is None:
        raise click.ClickException(f"未找到 delivery target: {name}")
    provider = cfg.delivery.providers.get(target.provider)
    if provider is None:
        raise click.ClickException(f"未找到 delivery provider: {target.provider}")

    if target.kind == "chat":
        target.resolved_id = target.id
    elif target.kind == "webhook":
        target.resolved_id = target.id or name
    elif target.id:
        target.resolved_id = target.id
    elif target.email and provider.type == "feishu_bot":
        target.resolved_id = resolve_user_by_email(
            target.provider, provider, target.email
        )
    else:
        raise click.ClickException("当前 target 无法解析，请配置 --open-id 或 --email")

    cfg.delivery.targets[name] = target
    save(cfg)
    payload = {"ok": True, "target": name, "resolved_id": target.resolved_id}
    if _json_output(ctx):
        _echo_json(payload)
    else:
        click.echo(f"{name}: resolved_id={target.resolved_id}")


@target_group.command("list")
@click.pass_context
def target_list(ctx: click.Context) -> None:
    """列出 delivery targets."""
    data = targets_data()
    if _json_output(ctx):
        _echo_json({"ok": True, "data": data})
        return
    if not data:
        click.echo("未配置 delivery target")
        return
    for name, target in data.items():
        dest = target.get("email") or target.get("id") or target.get("resolved_id")
        click.echo(
            f"{name}: {target['kind']} provider={target['provider']} recipient={dest}"
        )


@delivery.group(name="route")
def route_group() -> None:
    """投递 route 管理."""


@route_group.command("add")
@click.argument("name")
@click.option(
    "--target", "targets", multiple=True, required=True, help="target 名称，可重复"
)
@click.option(
    "--format",
    "message_format",
    type=click.Choice(["text", "post", "markdown", "markdown_v2"]),
    default="post",
)
@click.option("--fail-fast", is_flag=True, help="任一 target 失败后停止后续发送")
@click.pass_context
def route_add(
    ctx: click.Context,
    name: str,
    targets: tuple[str, ...],
    message_format: str,
    fail_fast: bool,
) -> None:
    """添加 route."""
    cfg = load()
    missing = [target for target in targets if target not in cfg.delivery.targets]
    if missing:
        raise click.ClickException(f"target 不存在: {', '.join(missing)}")
    cfg.delivery.routes[name] = DeliveryRouteConfig(
        targets=list(targets),
        format=message_format,  # type: ignore[arg-type]
        fail_fast=fail_fast,
    )
    save(cfg)
    if _json_output(ctx):
        _echo_json({"ok": True, "route": name, "message": "route 已保存"})
    else:
        click.echo(f"route 已保存: {name}")


@route_group.command("list")
@click.pass_context
def route_list(ctx: click.Context) -> None:
    """列出 delivery routes."""
    data = routes_data()
    if _json_output(ctx):
        _echo_json({"ok": True, "data": data})
        return
    if not data:
        click.echo("未配置 delivery route")
        return
    for name, route in data.items():
        click.echo(
            f"{name}: targets={','.join(route['targets'])} format={route['format']}"
        )


@delivery.command("send")
@click.option("--target", "target_name", help="发送到单个 target")
@click.option("--route", "route_name", help="发送到 route 下所有 targets")
@click.option("--text", help="发送文本")
@click.option("--markdown", "markdown_text", help="发送 Markdown 文本")
@click.option(
    "--markdown-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="读取 Markdown 文件并发送",
)
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="上传并发送文件附件（飞书 / 企业微信 provider）",
)
@click.option("--title", help="post 标题")
@click.option(
    "--format",
    "message_format",
    type=click.Choice(["text", "post", "markdown", "markdown_v2"]),
)
@click.option("--idempotency-key", help="飞书消息幂等 key")
@click.pass_context
def send_cmd(
    ctx: click.Context,
    target_name: str | None,
    route_name: str | None,
    text: str | None,
    markdown_text: str | None,
    markdown_file: Path | None,
    file_path: Path | None,
    title: str | None,
    message_format: str | None,
    idempotency_key: str | None,
) -> None:
    """发送消息."""
    if bool(target_name) == bool(route_name):
        raise click.ClickException("--target 和 --route 必须且只能指定一个")
    content_flags = [
        text is not None,
        markdown_text is not None,
        markdown_file is not None,
        file_path is not None,
    ]
    if sum(content_flags) != 1:
        raise click.ClickException(
            "--text、--markdown、--markdown-file、--file 必须且只能指定一个"
        )

    if file_path is not None:
        default_format = "file"
        message_text = ""
    elif markdown_file is not None:
        message_text = markdown_file.read_text(encoding="utf-8")
        default_format = "markdown"
    elif markdown_text is not None:
        message_text = markdown_text
        default_format = "markdown"
    else:
        assert text is not None
        message_text = text
        default_format = "post"

    if target_name:
        targets = [target_name]
        fail_fast = False
        fmt = message_format or default_format
    else:
        assert route_name is not None
        route, targets = route_targets(route_name)
        fail_fast = route.fail_fast
        if message_format:
            fmt = message_format
        elif default_format == "markdown":
            fmt = route.format if route.format == "markdown_v2" else "markdown"
        else:
            fmt = route.format

    if file_path is not None:
        results = send_file_targets(
            targets,
            file_path,
            fail_fast=fail_fast,
            idempotency_key=idempotency_key,
        )
    else:
        message = DeliveryMessage(
            format=cast(MessageFormat, fmt),
            text=message_text,
            title=title,
        )
        results = send_targets(
            targets,
            message,
            fail_fast=fail_fast,
            idempotency_key=idempotency_key,
        )

    payload = result_payload(results)
    if _json_output(ctx):
        _echo_json(payload)
    else:
        click.echo(payload["message"])
        for item in payload["data"]["results"]:  # type: ignore[index]
            assert isinstance(item, dict)
            status = "ok" if item["ok"] else f"failed: {item['error']}"
            click.echo(f"  {item['target']}: {status}")


@delivery.command("test")
@click.option("--target", "target_name", help="发送到单个 target")
@click.option("--route", "route_name", help="发送到 route 下所有 targets")
@click.pass_context
def test_cmd(
    ctx: click.Context,
    target_name: str | None,
    route_name: str | None,
) -> None:
    """发送测试消息."""
    ctx.invoke(
        send_cmd,
        target_name=target_name,
        route_name=route_name,
        text="stock-news delivery 测试消息",
        markdown_text=None,
        markdown_file=None,
        file_path=None,
        title="stock-news",
        message_format="text",
        idempotency_key=None,
    )
