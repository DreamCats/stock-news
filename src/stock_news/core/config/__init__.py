"""配置加载、保存和局部修改的 core API。"""

from stock_news.core.config.store import YAMLConfigStore, set_nested_value

__all__ = ["YAMLConfigStore", "set_nested_value"]
