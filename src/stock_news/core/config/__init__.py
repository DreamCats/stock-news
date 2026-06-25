"""配置加载、保存和局部修改的 core API。

这里用轻量 wrapper 暴露 runtime 能力，避免导入 store 时触发 runtime 循环导入。
"""

from pathlib import Path
from typing import TYPE_CHECKING

from stock_news.core.config.store import YAMLConfigStore, set_nested_value

if TYPE_CHECKING:
    from stock_news.models import AppConfig

CONFIG_DIR = Path.home() / ".config" / "stock-news"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load() -> "AppConfig":
    """延迟加载运行时配置。"""

    from stock_news.core.config.runtime import load as _load

    return _load()


def save(cfg: "AppConfig") -> None:
    """延迟保存运行时配置。"""

    from stock_news.core.config.runtime import save as _save

    _save(cfg)


def set_nested(cfg: "AppConfig", key: str, value: str) -> "AppConfig":
    """延迟执行点号路径配置修改。"""

    from stock_news.core.config.runtime import set_nested as _set_nested

    return _set_nested(cfg, key, value)


__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "YAMLConfigStore",
    "load",
    "save",
    "set_nested",
    "set_nested_value",
]
