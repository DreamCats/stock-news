"""统一 CLI 入口."""

from __future__ import annotations

import sys
import traceback

import click

from stock_news import __version__
from stock_news.commands.analyze_cli import analyze
from stock_news.commands.backfill_cli import backfill
from stock_news.commands.config_cli import config
from stock_news.commands.data_cli import data
from stock_news.commands.delivery import delivery
from stock_news.commands.fetch_cli import fetch
from stock_news.commands.llm_cli import llm
from stock_news.commands.market_cli import market
from stock_news.commands.schedule_cmd import schedule
from stock_news.commands.source_cli import source
from stock_news.commands.strategy_cli import strategy
from stock_news.commands.workflow_cli import workflow


@click.group()
@click.version_option(version=__version__, prog_name="sn")
@click.option("--json", "json_output", is_flag=True, help="JSON 格式输出")
@click.option("--verbose", is_flag=True, help="详细输出（显示完整错误栈）")
@click.pass_context
def main(ctx: click.Context, json_output: bool, verbose: bool) -> None:
    """投研信息流 CLI 工具.

    \b
    数据采集：
      sn fetch --source all --last 30m       # 拉取最近 30 分钟消息
      sn fetch --source 个人消息 --start 20260523090000 --end 20260523113000
      sn fetch --source all --date today --time-range 09:00-23:00

    \b
    数据查询：
      sn data stats --date today             # 今日数据统计
      sn data list --date today              # 列出今日消息
      sn data dedup --date today --dry-run   # 预览去重

    \b
    消息分析：
      sn analyze classify --date today       # LLM 消息分类
      sn analyze classify --date today --no-llm  # 规则降级
      sn analyze extract --date today        # 推荐抽取
      sn analyze opinion --date today        # 观点链归并
      sn analyze show --date today           # 查看分析摘要

    \b
    源头雷达：
      sn source scan --start 2026-05-01 --end 2026-05-13

    \b
    LLM 管理：
      sn llm add deepseek --base-url ... --model ... --api-key ...
      sn llm list                            # 查看 provider
      sn llm test                            # 测试连通性

    \b
    配置管理：
      sn config show                         # 查看配置
      sn config set api.timeout 60           # 修改配置

    \b
    JSON 输出（Agent 友好）：
      sn --json data stats --date today
      sn --json fetch --source all --last 30m
    """
    ctx.ensure_object(dict)
    ctx.obj["json_output"] = json_output
    ctx.obj["verbose"] = verbose


def _register_commands() -> None:
    main.add_command(fetch)
    main.add_command(data)
    main.add_command(backfill)
    main.add_command(analyze)
    main.add_command(strategy)
    main.add_command(workflow)
    main.add_command(source)
    main.add_command(llm)
    main.add_command(market)
    main.add_command(config)
    main.add_command(schedule)
    main.add_command(delivery)


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
