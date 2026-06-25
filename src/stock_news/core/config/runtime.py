"""运行时配置入口。

这里负责把默认配置路径、分文件配置加载和点号路径修改收敛到 core/config。
"""

from __future__ import annotations

from pathlib import Path

from stock_news.core.config.store import set_nested_value
from stock_news.models import AppConfig
from stock_news.usecases.configs.paths import ConfigPaths
from stock_news.usecases.configs.service import load_app_config, save_app_config

CONFIG_DIR = Path.home() / ".config" / "stock-news"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
_ROOT_ALIASES = {
    "llm": "models",
    "api": "wechat",
    "market": "tushare",
    "delivery": "channel",
}


def load() -> AppConfig:
    """加载运行时应用配置。"""

    return load_app_config(ConfigPaths.from_legacy_file(CONFIG_FILE))


def save(cfg: AppConfig) -> None:
    """保存运行时应用配置。"""

    save_app_config(ConfigPaths.from_legacy_file(CONFIG_FILE), cfg)


def set_nested(cfg: AppConfig, key: str, value: str) -> AppConfig:
    """通过点号路径设置配置项，如 wechat.timeout -> cfg.wechat.timeout。"""

    key = _normalize_key(key)
    data = cfg.model_dump(mode="json")
    set_nested_value(data, key, value)
    return AppConfig.model_validate(data)


def _normalize_key(key: str) -> str:
    """兼容旧配置根字段名。"""

    root, sep, rest = key.partition(".")
    normalized = _ROOT_ALIASES.get(root, root)
    if not sep:
        return normalized
    return f"{normalized}.{rest}"
