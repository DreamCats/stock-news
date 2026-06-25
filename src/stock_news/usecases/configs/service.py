"""分文件配置加载和保存用例。

本用例把旧的单文件配置迁移为按业务域拆分的 YAML：
模型、微信数据源、Tushare、公开研究源、阿里云、定时任务、渠道和催化词。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from stock_news.core.config.store import YAMLConfigStore
from stock_news.models import AppConfig
from stock_news.usecases.configs.models import (
    AlyConfigFile,
    CatalystsConfigFile,
    ChannelConfigFile,
    ModelProvidersConfigFile,
    ResearchSourcesConfigFile,
    ScheduleConfigFile,
    TushareConfigFile,
    WechatSourceConfigFile,
)
from stock_news.usecases.configs.paths import ConfigPaths


@dataclass(frozen=True)
class SplitConfigFiles:
    """配置拆分后的文件清单。"""

    model_providers: Path
    wechat_source: Path
    tushare: Path
    research_sources: Path
    aly: Path
    schedule: Path
    channel: Path
    catalysts: Path


def config_files(paths: ConfigPaths) -> SplitConfigFiles:
    """返回当前配置根目录下的分文件清单。"""

    return SplitConfigFiles(
        model_providers=paths.model_providers_file,
        wechat_source=paths.wechat_source_file,
        tushare=paths.tushare_file,
        research_sources=paths.research_sources_file,
        aly=paths.aly_file,
        schedule=paths.schedule_file,
        channel=paths.channel_file,
        catalysts=paths.catalysts_file,
    )


def load_app_config(paths: ConfigPaths) -> AppConfig:
    """加载分文件配置，并兼容读取旧 config.yaml。"""

    cfg = _load_legacy(paths.legacy_file)

    if paths.model_providers_file.exists():
        cfg.models = _store(paths.model_providers_file, ModelProvidersConfigFile).load(
            ModelProvidersConfigFile
        )
    if paths.wechat_source_file.exists():
        cfg.wechat = _store(paths.wechat_source_file, WechatSourceConfigFile).load(
            WechatSourceConfigFile
        )
    if paths.tushare_file.exists():
        cfg.tushare = _store(paths.tushare_file, TushareConfigFile).load(
            TushareConfigFile
        )
    if paths.research_sources_file.exists():
        cfg.research_sources = _store(
            paths.research_sources_file, ResearchSourcesConfigFile
        ).load(ResearchSourcesConfigFile)
    if paths.aly_file.exists():
        cfg.aly = _store(paths.aly_file, AlyConfigFile).load(AlyConfigFile)
    if paths.schedule_file.exists():
        cfg.schedule = _store(paths.schedule_file, ScheduleConfigFile).load(
            ScheduleConfigFile
        )
    if paths.channel_file.exists():
        cfg.channel = _store(paths.channel_file, ChannelConfigFile).load(
            ChannelConfigFile
        )
    if paths.catalysts_file.exists():
        cfg.catalysts = _store(paths.catalysts_file, CatalystsConfigFile).load(
            CatalystsConfigFile
        )
    return cfg


def save_app_config(paths: ConfigPaths, cfg: AppConfig) -> None:
    """保存 AppConfig，把各配置域写入各自文件。"""

    paths.split_dir.mkdir(parents=True, exist_ok=True)
    _store(paths.model_providers_file, ModelProvidersConfigFile).save(
        ModelProvidersConfigFile.model_validate(cfg.models.model_dump(mode="json")),
        mode=0o600,
    )
    _store(paths.wechat_source_file, WechatSourceConfigFile).save(
        WechatSourceConfigFile.model_validate(cfg.wechat.model_dump(mode="json")),
        mode=0o600,
    )
    _store(paths.tushare_file, TushareConfigFile).save(
        TushareConfigFile.model_validate(cfg.tushare.model_dump(mode="json")),
        mode=0o600,
    )
    _store(paths.research_sources_file, ResearchSourcesConfigFile).save(
        ResearchSourcesConfigFile.model_validate(
            cfg.research_sources.model_dump(mode="json")
        ),
        mode=0o600,
    )
    _store(paths.aly_file, AlyConfigFile).save(
        AlyConfigFile.model_validate(cfg.aly.model_dump(mode="json")),
        mode=0o600,
    )
    _store(paths.schedule_file, ScheduleConfigFile).save(
        ScheduleConfigFile.model_validate(cfg.schedule.model_dump(mode="json")),
        mode=0o600,
    )
    _store(paths.channel_file, ChannelConfigFile).save(
        ChannelConfigFile.model_validate(cfg.channel.model_dump(mode="json")),
        mode=0o600,
    )
    _store(paths.catalysts_file, CatalystsConfigFile).save(
        CatalystsConfigFile.model_validate(cfg.catalysts.model_dump(mode="json")),
        mode=0o600,
    )


def _store(path: Path, model_type: type[Any]) -> YAMLConfigStore[Any]:
    return YAMLConfigStore(path, model_type)


def _load_legacy(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件必须是 YAML object: {path}")
    return AppConfig.model_validate(raw)
