"""配置管理命令."""

from __future__ import annotations

import json

import click

from stock_news.common.config import CONFIG_FILE, load, save, set_nested
from stock_news.usecases.configs.paths import ConfigPaths
from stock_news.usecases.configs.service import config_files


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
        files = config_files(ConfigPaths.from_legacy_file(CONFIG_FILE))
        click.echo("配置文件:")
        click.echo(f"  models: {files.model_providers}")
        click.echo(f"  wechat: {files.wechat_source}")
        click.echo(f"  tushare: {files.tushare}")
        click.echo(f"  schedule: {files.schedule}")
        click.echo(f"  channel: {files.channel}")
        click.echo("")
        click.echo(f"默认模型: {cfg.models.default_provider or '未配置'}")
        click.echo(f"模型供应商: {', '.join(cfg.models.providers) or '未配置'}")
        click.echo(f"微信 API: {cfg.wechat.base_url}")
        click.echo(f"微信 DB: {cfg.wechat.db_path}")
        click.echo(f"微信数据源: {', '.join(cfg.wechat.sources)}")
        click.echo(f"Tushare API: {cfg.tushare.tushare_api_url or '未配置'}")
        click.echo(f"Market DB: {cfg.tushare.db_path}")
        click.echo(f"定时任务数: {len(cfg.schedule.jobs)}")
        click.echo(f"渠道 providers: {', '.join(cfg.channel.providers) or '未配置'}")


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
