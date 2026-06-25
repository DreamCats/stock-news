"""配置文件模板生成用例。

这里放可直接渲染成 YAML 的配置模板，避免 CLI、文档和测试各写一份示例。
"""

from __future__ import annotations

import yaml

from stock_news.models import LLMProviderConfig
from stock_news.usecases.configs.models import (
    AlyConfigFile,
    ChannelConfigFile,
    ModelProvidersConfigFile,
    ScheduleConfigFile,
    TushareConfigFile,
    WechatSourceConfigFile,
)


def default_model_providers_config() -> ModelProvidersConfigFile:
    """生成 glm/kimi/mimo/minimax 四个模型供应商的默认模板。"""

    return ModelProvidersConfigFile(
        default_provider="mimo",
        providers={
            "glm": _provider("<glm-base-url>/v1", "<glm-api-key>", "<glm-model>"),
            "kimi": _provider("<kimi-base-url>/v1", "<kimi-api-key>", "<kimi-model>"),
            "mimo": _provider("<mimo-base-url>/v1", "<mimo-api-key>", "<mimo-model>"),
            "minimax": _provider(
                "<minimax-base-url>/v1",
                "<minimax-api-key>",
                "<minimax-model>",
            ),
        },
        task_routing={
            "classify": "glm",
            "extract": "kimi",
            "opinion": "kimi",
            "source_extract": "kimi",
            "source_brief": "kimi",
        },
        provider_pools={
            "source_extract": ["kimi", "glm", "mimo", "minimax"],
            "nightly": ["kimi", "minimax", "mimo"],
        },
    )


def render_model_providers_template() -> str:
    """把模型供应商模板渲染成 models.yaml 内容。"""

    data = default_model_providers_config().model_dump(mode="json")
    return _dump_yaml(data)


def default_wechat_source_config() -> WechatSourceConfigFile:
    """生成微信数据源配置模板。"""

    return WechatSourceConfigFile(
        base_url="https://<wechat-api-base-url>",
        db_path="~/.config/stock-news/wechat.db",
        sources=["个人消息", "个人群"],
        timeout=30,
    )


def render_wechat_source_template() -> str:
    """把微信数据源配置模板渲染成 wechat.yaml 内容。"""

    data = default_wechat_source_config().model_dump(mode="json")
    return _dump_yaml(data)


def default_tushare_config() -> TushareConfigFile:
    """生成 Tushare 配置模板。"""

    return TushareConfigFile(
        tushare_api_url="https://<tushare-proxy-base-url>",
        token="",
        db_path="~/.config/stock-news/market.db",
        timeout=30,
    )


def render_tushare_template() -> str:
    """把 Tushare 模板渲染成 tushare.yaml 内容。"""

    data = default_tushare_config().model_dump(mode="json")
    return _dump_yaml(data)


def default_aly_config() -> AlyConfigFile:
    """生成阿里云配置模板。"""

    return AlyConfigFile(
        host="<aliyun-host>",
        user="root",
        password="",
        port=22,
        remote_dir="/usr/share/caddy/stock-news",
        url_prefix="http://<aliyun-host>/stock-news",
        sshpass_path="sshpass",
    )


def render_aly_template() -> str:
    """把阿里云模板渲染成 aly.yaml 内容。"""

    data = default_aly_config().model_dump(mode="json")
    return _dump_yaml(data)


def default_schedule_config() -> ScheduleConfigFile:
    """生成项目内固定定时任务配置模板。"""

    return ScheduleConfigFile()


def render_schedule_template() -> str:
    """把定时任务模板渲染成 schedule.yaml 内容。"""

    data = default_schedule_config().model_dump(mode="json")
    return _dump_yaml(data)


def default_channel_config() -> ChannelConfigFile:
    """生成渠道配置模板，保留 provider、target、route 三段。"""

    return ChannelConfigFile.model_validate(
        {
            "providers": {
                "feishu-main": {
                    "type": "feishu_bot",
                    "app_id": "<feishu-app-id>",
                    "app_secret": "<feishu-app-secret>",
                    "base_url": "https://open.feishu.cn",
                    "timeout": 30,
                },
                "wecom-main": {
                    "type": "wecom_bot",
                    "webhook_url": "<wecom-webhook-url>",
                    "timeout": 30,
                },
            },
            "targets": {
                "feishu-user": {
                    "provider": "feishu-main",
                    "kind": "user",
                    "email": "<user-email>",
                },
                "wecom-group": {
                    "provider": "wecom-main",
                    "kind": "webhook",
                },
            },
            "routes": {
                "default": {
                    "targets": ["feishu-user", "wecom-group"],
                    "format": "markdown",
                    "fail_fast": False,
                },
            },
        }
    )


def render_channel_template() -> str:
    """把渠道配置模板渲染成 channel.yaml 内容。"""

    data = default_channel_config().model_dump(
        mode="json",
        exclude_defaults=True,
        exclude_none=True,
    )
    return _dump_yaml(data)


def _dump_yaml(data: dict[str, object]) -> str:
    return yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _provider(base_url: str, api_key: str, model: str) -> LLMProviderConfig:
    return LLMProviderConfig(
        api="anthropic-messages",
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=None,
        temperature=0.1,
        timeout=300.0,
    )
