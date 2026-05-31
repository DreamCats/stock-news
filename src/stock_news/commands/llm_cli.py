"""llm 命令注册."""

from __future__ import annotations

import click


@click.group()
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
def llm_add(
    ctx: click.Context,
    name: str,
    base_url: str,
    model: str,
    api_key: str,
    set_default: bool,
) -> None:
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
