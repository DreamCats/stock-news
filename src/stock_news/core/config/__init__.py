"""配置加载、保存和局部修改的 core API。"""

from stock_news.core.config.runtime import (
    CONFIG_DIR,
    CONFIG_FILE,
    load,
    save,
    set_nested,
)
from stock_news.core.config.store import YAMLConfigStore, set_nested_value

__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "YAMLConfigStore",
    "load",
    "save",
    "set_nested",
    "set_nested_value",
]
