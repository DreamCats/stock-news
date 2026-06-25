"""配置业务用例。

这里定义 stock-news 配置如何拆分、加载、保存和生成模板。
"""

from stock_news.usecases.configs.paths import ConfigPaths
from stock_news.usecases.configs.service import (
    SplitConfigFiles,
    config_files,
    load_app_config,
    save_app_config,
)
from stock_news.usecases.configs.templates import (
    default_aly_config,
    default_catalysts_config,
    default_channel_config,
    default_model_providers_config,
    default_schedule_config,
    default_tushare_config,
    default_wechat_source_config,
    render_aly_template,
    render_catalysts_template,
    render_channel_template,
    render_model_providers_template,
    render_schedule_template,
    render_tushare_template,
    render_wechat_source_template,
)

__all__ = [
    "ConfigPaths",
    "SplitConfigFiles",
    "config_files",
    "default_aly_config",
    "default_catalysts_config",
    "default_channel_config",
    "default_model_providers_config",
    "default_schedule_config",
    "default_tushare_config",
    "default_wechat_source_config",
    "load_app_config",
    "render_aly_template",
    "render_catalysts_template",
    "render_channel_template",
    "render_model_providers_template",
    "render_schedule_template",
    "render_tushare_template",
    "render_wechat_source_template",
    "save_app_config",
]
