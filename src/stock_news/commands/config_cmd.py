"""配置管理命令."""

from __future__ import annotations

import json

import click

from stock_news.core.config import CONFIG_FILE, load, save, set_nested
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
        click.echo(f"  aly: {files.aly}")
        click.echo(f"  schedule: {files.schedule}")
        click.echo(f"  channel: {files.channel}")
        click.echo(f"  catalysts: {files.catalysts}")
        click.echo("")
        click.echo(f"默认模型: {cfg.models.default_provider or '未配置'}")
        click.echo(f"模型供应商: {', '.join(cfg.models.providers) or '未配置'}")
        click.echo(f"微信 API: {cfg.wechat.base_url}")
        click.echo(f"微信 DB: {cfg.wechat.db_path}")
        click.echo(f"微信数据源: {', '.join(cfg.wechat.sources)}")
        click.echo(f"Tushare API: {cfg.tushare.tushare_api_url or '未配置'}")
        click.echo(f"Market DB: {cfg.tushare.db_path}")
        click.echo(f"阿里云: {cfg.aly.user}@{cfg.aly.host}:{cfg.aly.port}")
        click.echo(f"阿里云目录: {cfg.aly.remote_dir or '未配置'}")
        click.echo(f"阿里云 URL: {cfg.aly.url_prefix or '未配置'}")
        click.echo(f"定时任务: {'启用' if cfg.schedule.enabled else '停用'}")
        click.echo(
            "微信定时: "
            f"{'启用' if cfg.schedule.wechat_fetch.enabled else '停用'} "
            f"every={cfg.schedule.wechat_fetch.every} "
            f"window={cfg.schedule.wechat_fetch.window}"
        )
        click.echo(
            "Tushare 定时: "
            f"{'启用' if cfg.schedule.tushare_sync.enabled else '停用'} "
            f"at={cfg.schedule.tushare_sync.at}"
        )
        click.echo(
            "催化 Excel 定时: "
            f"{'启用' if cfg.schedule.catalyst_stock_excel.enabled else '停用'} "
            f"every={cfg.schedule.catalyst_stock_excel.every} "
            f"window={cfg.schedule.catalyst_stock_excel.window} "
            f"active={cfg.schedule.catalyst_stock_excel.active_start}-"
            f"{cfg.schedule.catalyst_stock_excel.active_end} "
            f"targets={', '.join(cfg.schedule.catalyst_stock_excel.channel_targets)}"
        )
        click.echo(
            "晚间 Top 逻辑定时: "
            f"{'启用' if cfg.schedule.evening_top_logic.enabled else '停用'} "
            f"at={cfg.schedule.evening_top_logic.at} "
            f"window={cfg.schedule.evening_top_logic.window_start}-"
            f"{cfg.schedule.evening_top_logic.window_end} "
            f"provider={cfg.schedule.evening_top_logic.provider} "
            f"top={cfg.schedule.evening_top_logic.top_candidates}->"
            f"{cfg.schedule.evening_top_logic.top_final} "
            f"targets={', '.join(cfg.schedule.evening_top_logic.channel_targets)}"
        )
        click.echo(f"渠道 providers: {', '.join(cfg.channel.providers) or '未配置'}")
        custom_count = len(
            [
                category
                for category in cfg.catalysts.custom_categories
                if category.enabled
            ]
        )
        click.echo(
            "催化词: "
            f"内置={'启用' if cfg.catalysts.builtin_enabled else '停用'} "
            f"覆盖分类={len(cfg.catalysts.categories)} "
            f"自定义分类={custom_count}"
        )


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
