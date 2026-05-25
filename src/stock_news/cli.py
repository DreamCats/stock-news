"""统一 CLI 入口."""

import sys
import traceback

import click

from stock_news import __version__


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


# -- fetch --


@main.command()
@click.option(
    "--source",
    "-s",
    default="all",
    help="数据源: 个人消息 / 个人群 / all",
)
@click.option("--start", help="开始时间，格式 yyyyMMddHHmmss")
@click.option("--end", help="结束时间，格式 yyyyMMddHHmmss")
@click.option("--last", help="拉取最近 N 分钟/小时，如 30m / 2h")
@click.option("--date", "date_str", help="日期: today / yesterday / 2026-05-25")
@click.option("--time-range", help="日内时间范围，如 09:00-23:00")
@click.option(
    "--slice-hours",
    type=int,
    default=1,
    help="按 N 小时切片拉取，默认 1（窗口小于切片则不切）",
)
@click.option("--workers", type=int, default=4, help="并发请求数，默认 4")
@click.option(
    "--refresh",
    is_flag=True,
    help="忽略切片缓存，强制重拉所有切片",
)
@click.pass_context
def fetch(
    ctx: click.Context,
    source: str,
    start: str | None,
    end: str | None,
    last: str | None,
    date_str: str | None,
    time_range: str | None,
    slice_hours: int,
    workers: int,
    refresh: bool,
) -> None:
    """拉取微信 API 消息."""
    from stock_news.commands.fetch import run_fetch

    run_fetch(
        source,
        start,
        end,
        last,
        date_str,
        time_range,
        ctx.obj["json_output"],
        slice_hours,
        workers,
        refresh,
    )


# -- data --


@main.group()
@click.pass_context
def data(ctx: click.Context) -> None:
    """本地数据查询."""
    pass


@data.command()
@click.option("--date", "-d", "date_str", default="today", help="日期: today / yesterday / 2026-05-23")
@click.pass_context
def stats(ctx: click.Context, date_str: str) -> None:
    """查看数据统计."""
    from stock_news.commands.data import stats as _stats

    _stats(date_str, ctx.obj["json_output"])


@data.command("list")
@click.option("--date", "-d", "date_str", default="today", help="日期: today / yesterday / 2026-05-23")
@click.option("--source", "-s", help="筛选数据源: 个人消息 / 个人群")
@click.pass_context
def data_list(ctx: click.Context, date_str: str, source: str | None) -> None:
    """列出消息."""
    from stock_news.commands.data import list_messages

    list_messages(date_str, source, ctx.obj["json_output"])


@data.command()
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--dry-run", is_flag=True, help="只预览，不执行")
@click.pass_context
def dedup(ctx: click.Context, date_str: str, dry_run: bool) -> None:
    """去重消息."""
    from stock_news.commands.data import dedup as _dedup

    _dedup(date_str, dry_run, ctx.obj["json_output"])


# -- analyze --


@main.group()
@click.pass_context
def analyze(ctx: click.Context) -> None:
    """消息分析（分类、抽取、观点链）."""
    pass


@analyze.command()
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--no-llm", is_flag=True, help="不使用 LLM，降级为规则分类")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def classify(ctx: click.Context, date_str: str, no_llm: bool, provider: str | None) -> None:
    """对消息做分类."""
    from stock_news.commands.analyze import classify as _classify

    _classify(date_str, no_llm, provider, ctx.obj["json_output"])


@analyze.command()
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def extract(ctx: click.Context, date_str: str, provider: str | None) -> None:
    """从推荐消息中抽取结构化字段."""
    from stock_news.commands.analyze import extract as _extract

    _extract(date_str, provider, ctx.obj["json_output"])


@analyze.command("opinion")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def opinion_cmd(ctx: click.Context, date_str: str, provider: str | None) -> None:
    """分析观点链变化."""
    from stock_news.commands.analyze import opinion as _opinion

    _opinion(date_str, provider, ctx.obj["json_output"])


@analyze.command("show")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.pass_context
def analyze_show(ctx: click.Context, date_str: str) -> None:
    """查看分析摘要."""
    from stock_news.commands.analyze import show_analysis

    show_analysis(date_str, ctx.obj["json_output"])


@analyze.command("pipeline")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--no-llm", is_flag=True, help="不使用 LLM，降级为规则分类")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def analyze_pipeline(ctx: click.Context, date_str: str, no_llm: bool, provider: str | None) -> None:
    """一键执行: 分类 → 抽取 → 回测."""
    from stock_news.commands.analyze import pipeline as _pipeline

    _pipeline(date_str, no_llm, provider, ctx.obj["json_output"])


@analyze.group("backtest", invoke_without_command=True)
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.pass_context
def analyze_backtest(ctx: click.Context, date_str: str) -> None:
    """回测推荐人胜率（需先 sn market init）."""
    if ctx.invoked_subcommand is not None:
        return
    from stock_news.commands.backtest import run_backtest

    run_backtest(date_str, ctx.obj["json_output"])


@analyze_backtest.command("refresh")
@click.option(
    "--as-of",
    "as_of_str",
    default="today",
    show_default=True,
    help="刷新到哪一天",
)
@click.option(
    "--window-days",
    type=click.IntRange(min=1),
    default=30,
    show_default=True,
    help="扫描最近 N 天推荐",
)
@click.pass_context
def analyze_backtest_refresh(
    ctx: click.Context,
    as_of_str: str,
    window_days: int,
) -> None:
    """刷新已成熟的 T+N 回测窗口."""
    from stock_news.commands.backtest import run_backtest_refresh

    run_backtest_refresh(as_of_str, window_days, ctx.obj["json_output"])


@analyze.command("backtest-summary")
@click.option("--top", "-n", type=int, default=None, help="只显示前 N 名")
@click.option(
    "--min-count",
    type=int,
    default=1,
    help="最少推荐次数（过滤样本量不足的）",
)
@click.option(
    "--window-days",
    type=click.IntRange(min=1),
    default=30,
    show_default=True,
    help="汇总最近 N 天",
)
@click.option("--all", "include_all", is_flag=True, help="汇总所有已有回测结果")
@click.pass_context
def analyze_backtest_summary(
    ctx: click.Context,
    top: int | None,
    min_count: int,
    window_days: int,
    include_all: bool,
) -> None:
    """汇总近期回测结果，输出推荐人滚动胜率."""
    from stock_news.commands.backtest import run_backtest_summary

    run_backtest_summary(
        ctx.obj["json_output"],
        top=top,
        min_count=min_count,
        window_days=None if include_all else window_days,
    )


# -- strategy --


@main.group()
@click.pass_context
def strategy(ctx: click.Context) -> None:
    """盘中策略快报."""
    pass


@strategy.command("generate")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option(
    "--window-minutes",
    type=click.IntRange(min=1),
    default=20,
    show_default=True,
    help="本轮窗口分钟数",
)
@click.option(
    "--top",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="最多输出候选机会数",
)
@click.pass_context
def strategy_generate(
    ctx: click.Context,
    date_str: str,
    window_minutes: int,
    top: int,
) -> None:
    """生成策略快报 JSON 和 Markdown."""
    from stock_news.commands.strategy import generate

    generate(date_str, window_minutes, top, ctx.obj["json_output"])


# -- llm --


@main.group()
@click.pass_context
def llm(ctx: click.Context) -> None:
    """LLM provider 管理."""
    pass


@llm.command("add")
@click.argument("name")
@click.option("--base-url", required=True, help="OpenAI 兼容接口地址")
@click.option("--model", required=True, help="模型名")
@click.option("--api-key", default="", help="API key")
@click.option("--default", "set_default", is_flag=True, help="设为默认")
@click.pass_context
def llm_add(ctx: click.Context, name: str, base_url: str, model: str, api_key: str, set_default: bool) -> None:
    """添加 LLM provider."""
    from stock_news.commands.llm_cmd import add_provider

    add_provider(name, base_url, model, api_key, set_default)


@llm.command("list")
@click.pass_context
def llm_list(ctx: click.Context) -> None:
    """列出 LLM provider."""
    from stock_news.commands.llm_cmd import list_providers

    list_providers(ctx.obj["json_output"])


@llm.command("set-default")
@click.argument("name")
@click.pass_context
def llm_set_default(ctx: click.Context, name: str) -> None:
    """设置默认 LLM provider."""
    from stock_news.commands.llm_cmd import set_default

    set_default(name)


@llm.command("test")
@click.option("--provider", "-p", help="指定 provider")
@click.pass_context
def llm_test(ctx: click.Context, provider: str | None) -> None:
    """测试 LLM 连通性."""
    from stock_news.commands.llm_cmd import test_provider

    test_provider(provider, ctx.obj["json_output"])


@llm.command("chat")
@click.argument("message")
@click.option("--provider", "-p", help="指定 provider")
@click.pass_context
def llm_chat(ctx: click.Context, message: str, provider: str | None) -> None:
    """直接与 LLM 对话（调试用）."""
    from stock_news.commands.llm_cmd import chat_cmd

    chat_cmd(message, provider, ctx.obj["json_output"])


@llm.command("route")
@click.argument("task")
@click.argument("provider")
@click.pass_context
def llm_route(ctx: click.Context, task: str, provider: str) -> None:
    """设置任务路由，如: sn llm route classify deepseek."""
    from stock_news.commands.llm_cmd import set_route

    set_route(task, provider)


# -- market --


@main.group()
@click.pass_context
def market(ctx: click.Context) -> None:
    """行情数据管理（Tushare + SQLite 缓存）."""
    pass


@market.command("set-token")
@click.argument("token")
def market_set_token(token: str) -> None:
    """设置 Tushare Pro token."""
    from stock_news.commands.market_cmd import set_token

    set_token(token)


@market.command("init")
@click.pass_context
def market_init(ctx: click.Context) -> None:
    """初始化: 同步股票列表 + 交易日历."""
    from stock_news.commands.market_cmd import init

    init(ctx.obj["json_output"])


@market.command("search")
@click.argument("keyword")
@click.pass_context
def market_search(ctx: click.Context, keyword: str) -> None:
    """股票名称搜索，如: sn market search 贵州茅台."""
    from stock_news.commands.market_cmd import search

    search(keyword, ctx.obj["json_output"])


@market.command("price")
@click.argument("ts_code")
@click.option("--start", "start_date", required=True, help="开始日期 YYYYMMDD")
@click.option("--end", "end_date", required=True, help="结束日期 YYYYMMDD")
@click.pass_context
def market_price(ctx: click.Context, ts_code: str, start_date: str, end_date: str) -> None:
    """查询/拉取日线行情，如: sn market price 600519.SH --start 20260101 --end 20260523."""
    from stock_news.commands.market_cmd import price

    price(ts_code, start_date, end_date, ctx.obj["json_output"])


@market.command("info")
@click.pass_context
def market_info(ctx: click.Context) -> None:
    """查看本地缓存统计."""
    from stock_news.commands.market_cmd import info

    info(ctx.obj["json_output"])


# -- config --


@main.group()
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


# -- schedule --


def _register_schedule_commands() -> None:
    from stock_news.commands.schedule_cmd import schedule

    main.add_command(schedule, "schedule")
    main.add_command(schedule, "sched")


def _register_delivery_commands() -> None:
    from stock_news.commands.delivery import delivery

    main.add_command(delivery, "delivery")


_register_schedule_commands()
_register_delivery_commands()


# -- entry --


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
