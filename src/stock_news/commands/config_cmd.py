"""配置管理命令."""

from __future__ import annotations

import json

import click

from stock_news.common.config import load, save, set_nested


def _masked(value: object) -> object:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(
                word in lowered for word in ("secret", "api_key", "token", "webhook")
            ):
                out[key] = "***" if item else item
            elif "password" in lowered:
                out[key] = "***" if item else item
            else:
                out[key] = _masked(item)
        return out
    if isinstance(value, list):
        return [_masked(item) for item in value]
    return value


def show(json_output: bool) -> None:
    cfg = load()
    if json_output:
        click.echo(
            json.dumps(
                _masked(cfg.model_dump(mode="json")), indent=2, ensure_ascii=False
            )
        )
    else:
        click.echo(f"API 地址: {cfg.api.base_url}")
        click.echo(f"数据源: {', '.join(cfg.api.sources)}")
        click.echo(f"超时: {cfg.api.timeout}s")
        click.echo(f"数据目录: {cfg.storage.data_dir}")
        click.echo(f"存储格式: {cfg.storage.format}")
        click.echo(f"Tushare API: {cfg.market.tushare_api_url or '直连'}")
        if cfg.delivery.providers:
            click.echo(f"Delivery providers: {', '.join(cfg.delivery.providers)}")


def set_value(key: str, value: str) -> None:
    cfg = load()
    cfg = set_nested(cfg, key, value)
    save(cfg)
    shown = (
        "***"
        if any(
            word in key.lower()
            for word in ("secret", "api_key", "token", "password", "webhook")
        )
        else value
    )
    click.echo(f"已设置 {key} = {shown}")
