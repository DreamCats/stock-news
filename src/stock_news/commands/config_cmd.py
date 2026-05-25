"""配置管理命令."""

from __future__ import annotations

import json

import click

from stock_news.common.config import load, save, set_nested


def show(json_output: bool) -> None:
    cfg = load()
    if json_output:
        click.echo(json.dumps(cfg.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        click.echo(f"API 地址: {cfg.api.base_url}")
        click.echo(f"数据源: {', '.join(cfg.api.sources)}")
        click.echo(f"超时: {cfg.api.timeout}s")
        click.echo(f"数据目录: {cfg.storage.data_dir}")
        click.echo(f"存储格式: {cfg.storage.format}")


def set_value(key: str, value: str) -> None:
    cfg = load()
    cfg = set_nested(cfg, key, value)
    save(cfg)
    click.echo(f"已设置 {key} = {value}")
