"""config 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def config(ctx: click.Context) -> None:
    """配置管理."""
    pass


@config.command()
@click.pass_context
def show(ctx: click.Context) -> None:
    """显示当前配置."""
    from stock_news.commands.config_cmd import show as _show

    _show(ctx.obj["json_output"])


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """设置配置项，如: sn config set api.timeout 60."""
    from stock_news.commands.config_cmd import set_value

    set_value(key, value)
