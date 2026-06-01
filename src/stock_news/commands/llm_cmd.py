"""LLM 配置与调试命令."""

from __future__ import annotations

import json
from typing import Literal

import click

from stock_news.common.config import load, save
from stock_news.models import LLMProviderConfig


def add_provider(
    name: str,
    base_url: str,
    model: str,
    api_key: str,
    api_type: Literal["openai", "openai-completions", "anthropic-messages"],
    raw_headers: tuple[str, ...],
    set_default: bool,
) -> None:
    headers: dict[str, str] = {}
    for raw in raw_headers:
        if ":" not in raw:
            raise click.ClickException("--header 格式必须是 Key:Value")
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise click.ClickException("--header 格式必须是 Key:Value")
        headers[key] = value

    cfg = load()
    cfg.llm.providers[name] = LLMProviderConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        api=api_type,
        headers=headers,
    )
    if set_default or not cfg.llm.default_provider:
        cfg.llm.default_provider = name
    save(cfg)
    click.echo(f"已添加 LLM provider: {name} ({model} @ {base_url})")
    if set_default or cfg.llm.default_provider == name:
        click.echo("已设为默认 provider")


def list_providers(json_output: bool) -> None:
    cfg = load()
    if json_output:
        data = {
            "default": cfg.llm.default_provider,
            "providers": {
                k: {
                    "base_url": v.base_url,
                    "api": v.api,
                    "model": v.model,
                    "timeout": v.timeout,
                    "headers": sorted(v.headers),
                }
                for k, v in cfg.llm.providers.items()
            },
            "task_routing": cfg.llm.task_routing,
            "provider_pools": cfg.llm.provider_pools,
        }
        click.echo(json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2))
    else:
        if not cfg.llm.providers:
            click.echo("未配置 LLM provider")
            click.echo(
                "使用: sn llm add <name> --base-url ... --model ... --api-key ..."
            )
            return
        click.echo(f"默认 provider: {cfg.llm.default_provider or '(未设置)'}\n")
        for name, p in cfg.llm.providers.items():
            marker = " *" if name == cfg.llm.default_provider else ""
            click.echo(
                f"  {name}{marker}: {p.model} [{p.api}] @ {p.base_url} "
                f"(timeout={p.timeout:g}s)"
            )
        if cfg.llm.task_routing:
            click.echo("\n任务路由:")
            for task, provider in cfg.llm.task_routing.items():
                click.echo(f"  {task}: {provider}")
        if cfg.llm.provider_pools:
            click.echo("\nProvider 池:")
            for task, providers in cfg.llm.provider_pools.items():
                click.echo(f"  {task}: {', '.join(providers)}")


def set_default(name: str) -> None:
    cfg = load()
    if name not in cfg.llm.providers:
        available = ", ".join(cfg.llm.providers) or "(无)"
        raise click.ClickException(f"Provider '{name}' 不存在，可用: {available}")
    cfg.llm.default_provider = name
    save(cfg)
    click.echo(f"已设置默认 LLM provider: {name}")


def test_provider(provider_name: str | None, json_output: bool) -> None:
    from stock_news.common.llm.client import test_connection

    result = test_connection(provider_name)
    if json_output:
        click.echo(
            json.dumps(
                {"ok": result["status"] == "ok", "data": result},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if result["status"] == "ok":
            click.echo(f"✓ {result['provider']} ({result['model']}): {result['reply']}")
        else:
            error = result.get("error", "未知错误")
            click.secho(
                f"✗ {result['provider']} ({result['model']}): {error}",
                fg="red",
            )


def chat_cmd(message: str, provider_name: str | None, json_output: bool) -> None:
    from stock_news.common.llm.client import chat

    reply = chat([{"role": "user", "content": message}], provider_name=provider_name)
    if json_output:
        click.echo(
            json.dumps(
                {"ok": True, "data": {"reply": reply}}, ensure_ascii=False, indent=2
            )
        )
    else:
        click.echo(reply)


def set_route(task: str, provider: str) -> None:
    cfg = load()
    if provider not in cfg.llm.providers:
        available = ", ".join(cfg.llm.providers) or "(无)"
        raise click.ClickException(f"Provider '{provider}' 不存在，可用: {available}")
    cfg.llm.task_routing[task] = provider
    save(cfg)
    click.echo(f"已设置 {task} -> {provider}")
