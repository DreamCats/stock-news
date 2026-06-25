"""配置数据模型。

当前项目只保留配置能力；这里集中声明模型供应商、微信数据源、
Tushare、定时任务和渠道配置的强类型结构。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_DURATION_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[smhd])$")
_CLOCK_RE = re.compile(r"^\d{2}:\d{2}$")


class WechatAuthConfig(BaseModel):
    """微信数据源 API 鉴权配置。"""

    type: Literal["none", "bearer", "api_key", "headers"] = "none"
    bearer_token: str = ""
    api_key: str = ""
    api_key_header: str = "Authorization"
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_auth(self) -> WechatAuthConfig:
        if self.type == "bearer" and not self.bearer_token:
            raise ValueError("bearer 鉴权必须配置 bearer_token")
        if self.type == "api_key" and not self.api_key:
            raise ValueError("api_key 鉴权必须配置 api_key")
        if self.type == "headers" and not self.headers:
            raise ValueError("headers 鉴权必须配置 headers")
        return self


class WechatFetchConfig(BaseModel):
    """微信数据源拉取默认参数。"""

    slice_hours: int = 1
    workers: int = 4
    retries: int = 1
    safety_margin_minutes: int = 5

    @model_validator(mode="after")
    def _validate_fetch_defaults(self) -> WechatFetchConfig:
        if self.slice_hours < 1:
            raise ValueError("slice_hours 必须大于等于 1")
        if self.workers < 1:
            raise ValueError("workers 必须大于等于 1")
        if self.retries < 0:
            raise ValueError("retries 必须大于等于 0")
        if self.safety_margin_minutes < 0:
            raise ValueError("safety_margin_minutes 必须大于等于 0")
        return self


class WechatSourceConfig(BaseModel):
    """微信数据源配置。"""

    base_url: str = "https://example.com/api"
    db_path: str = "~/.config/stock-news/wechat.db"
    sources: list[str] = Field(default_factory=lambda: ["个人消息", "个人群"])
    timeout: int = 30
    auth: WechatAuthConfig = Field(default_factory=WechatAuthConfig)
    fetch: WechatFetchConfig = Field(default_factory=WechatFetchConfig)


class LLMProviderConfig(BaseModel):
    """单个模型供应商配置。"""

    base_url: str
    api_key: str = ""
    model: str
    api: Literal["openai", "openai-completions", "anthropic-messages"] = "openai"
    headers: dict[str, str] = Field(default_factory=dict)
    max_tokens: int | None = None
    temperature: float = 0.1
    timeout: float = 300.0


class LLMConfig(BaseModel):
    """模型供应商总配置。"""

    default_provider: str = ""
    providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    task_routing: dict[str, str] = Field(default_factory=dict)
    provider_pools: dict[str, list[str]] = Field(default_factory=dict)


class TushareConfig(BaseModel):
    """Tushare 代理配置。"""

    tushare_api_url: str = ""
    token: str = ""
    db_path: str = "~/.config/stock-news/market.db"
    timeout: int = 30


class ScheduleJobConfig(BaseModel):
    """单个定时任务的配置，不包含执行状态。"""

    id: str
    command: str
    every: str | None = None
    at: str | None = None
    weekdays: str | None = None
    active_hours: str | None = None
    timeout: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_schedule(self) -> ScheduleJobConfig:
        if bool(self.every) == bool(self.at):
            raise ValueError("job 必须且只能配置 every 或 at")
        if self.every:
            _validate_duration(self.every)
        if self.at:
            _validate_clock(self.at)
        if self.timeout:
            _validate_duration(self.timeout)
        if self.active_hours:
            _validate_active_hours(self.active_hours)
        return self


class ScheduleConfig(BaseModel):
    """定时任务配置文件。"""

    tick_interval: str = "5m"
    jobs: list[ScheduleJobConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_schedule_file(self) -> ScheduleConfig:
        _validate_duration(self.tick_interval)
        seen: set[str] = set()
        for job in self.jobs:
            if job.id in seen:
                raise ValueError(f"重复的 schedule job id: {job.id}")
            seen.add(job.id)
        return self


class DeliveryProviderConfig(BaseModel):
    """单个渠道 provider 配置。"""

    type: Literal["feishu_bot", "wecom_bot"]
    app_id: str = ""
    app_secret: str = ""
    webhook_url: str = ""
    base_url: str = "https://open.feishu.cn"
    timeout: int = 30

    @model_validator(mode="after")
    def _validate_provider(self) -> DeliveryProviderConfig:
        if self.type == "feishu_bot":
            if not self.app_id or not self.app_secret:
                raise ValueError("feishu_bot provider 必须配置 app_id 和 app_secret")
        elif not self.webhook_url:
            raise ValueError("wecom_bot provider 必须配置 webhook_url")
        return self


class DeliveryTargetConfig(BaseModel):
    """渠道投递目标配置。"""

    provider: str
    kind: Literal["user", "chat", "webhook"]
    id: str | None = None
    email: str | None = None
    name: str | None = None
    resolved_id: str | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> DeliveryTargetConfig:
        if self.kind == "chat":
            if not self.id:
                raise ValueError("chat target 必须配置 id/chat_id")
        elif self.kind == "webhook":
            pass
        elif not any([self.id, self.email, self.name, self.resolved_id]):
            raise ValueError("user target 必须配置 open_id、email、name 或 resolved_id")
        return self


class DeliveryRouteConfig(BaseModel):
    """渠道路由配置。"""

    targets: list[str] = Field(default_factory=list)
    format: Literal["text", "post", "markdown", "markdown_v2"] = "post"
    fail_fast: bool = False


class ChannelConfig(BaseModel):
    """渠道配置，包含 provider、target 和 route。"""

    providers: dict[str, DeliveryProviderConfig] = Field(default_factory=dict)
    targets: dict[str, DeliveryTargetConfig] = Field(default_factory=dict)
    routes: dict[str, DeliveryRouteConfig] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """聚合后的应用配置，兼容旧字段名并映射到新分层。"""

    model_config = ConfigDict(extra="ignore")

    models: LLMConfig = Field(default_factory=LLMConfig)
    wechat: WechatSourceConfig = Field(default_factory=WechatSourceConfig)
    tushare: TushareConfig = Field(default_factory=TushareConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    channel: ChannelConfig = Field(default_factory=ChannelConfig)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        aliases = {
            "llm": "models",
            "api": "wechat",
            "market": "tushare",
            "delivery": "channel",
        }
        for old_key, new_key in aliases.items():
            if old_key in migrated and new_key not in migrated:
                migrated[new_key] = migrated[old_key]
        return migrated


def _validate_duration(value: str) -> None:
    if not _DURATION_RE.match(value.strip()):
        raise ValueError(f"非法 duration: {value}")


def _validate_clock(value: str) -> None:
    if not _CLOCK_RE.match(value.strip()):
        raise ValueError(f"非法时间格式，期望 HH:MM: {value}")
    datetime.strptime(value, "%H:%M")


def _validate_active_hours(value: str) -> None:
    parts = value.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"非法 active_hours，期望 HH:MM-HH:MM: {value}")
    _validate_clock(parts[0])
    _validate_clock(parts[1])
