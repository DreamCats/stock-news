"""统一 CLI 入口."""

from __future__ import annotations

import sys
import traceback

import click

from stock_news import __version__
from stock_news.commands.config_cli import config
from stock_news.commands.wechat_cli import wechat


@click.group()
@click.version_option(version=__version__, prog_name="sn")
@click.option("--json", "json_output", is_flag=True, help="JSON 格式输出")
@click.option("--verbose", is_flag=True, help="详细输出（显示完整错误栈）")
@click.pass_context
def main(ctx: click.Context, json_output: bool, verbose: bool) -> None:
    """投研信息流配置 CLI.

    \b
    配置管理：
      sn config show                         # 查看配置
      sn config set wechat.timeout 60        # 修改配置

    \b
    微信数据源：
      sn wechat fetch --last 30m             # 拉取最近 30 分钟原始消息

    \b
    JSON 输出（Agent 友好）：
      sn --json config show
    """
    ctx.ensure_object(dict)
    ctx.obj["json_output"] = json_output
    ctx.obj["verbose"] = verbose


def _register_commands() -> None:
    main.add_command(config)
    main.add_command(wechat)


_register_commands()


def cli_main() -> None:
    """入口函数，统一捕获异常."""
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        verbose = "--verbose" in sys.argv
        if verbose:
            traceback.print_exc()
        else:
            click.secho(f"错误: {e}", fg="red", err=True)
            click.secho("提示: 使用 --verbose 查看完整错误栈", fg="yellow", err=True)
        sys.exit(1)
