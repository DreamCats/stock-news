"""分文件配置模型。

这里只做配置文件边界命名：每个类对应一个 YAML 文件，
具体字段结构复用顶层配置模型。
"""

from __future__ import annotations

from stock_news.models import (
    ChannelConfig,
    LLMConfig,
    ScheduleConfig,
    TushareConfig,
    WechatSourceConfig,
)


class ModelProvidersConfigFile(LLMConfig):
    """models.yaml：模型供应商、默认模型、任务路由和 provider 池。"""


class WechatSourceConfigFile(WechatSourceConfig):
    """wechat.yaml：微信数据源 API、鉴权和拉取默认参数。"""


class TushareConfigFile(TushareConfig):
    """tushare.yaml：Tushare 代理 API 和访问参数。"""


class ScheduleConfigFile(ScheduleConfig):
    """schedule.yaml：定时任务定义。"""


class ChannelConfigFile(ChannelConfig):
    """channel.yaml：飞书和企微 provider、target、route。"""
