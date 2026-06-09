"""共享数据模型."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class MessageSource(str, Enum):
    PERSONAL = "个人消息"
    GROUP = "个人群"


class RawMessage(BaseModel):
    source: str
    sender: str
    message_time: datetime
    raw_content: str
    group_name: str | None = None
    fetch_time: datetime
    fetch_window: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message_id(self) -> str:
        key = f"{self.sender}|{self.message_time.isoformat()}|{self.raw_content}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


class MessageCategory(str, Enum):
    RECOMMENDATION = "recommendation"
    RESEARCH = "research"
    EVENT = "event"
    TOOL = "tool"
    NOISE = "noise"


class ClassifiedMessage(BaseModel):
    message_id: str
    source: str = ""
    sender: str = ""
    message_time: datetime | None = None
    category: MessageCategory
    confidence: float
    reason: str
    llm_provider: str | None = None


class Recommendation(BaseModel):
    message_id: str
    source: str = ""
    sender: str
    message_time: datetime | None = None
    target_type: str = "stock"
    target_name: str | None = None
    ticker: str
    market: str | None = None
    raw_action: str | None = None
    normalized_action: str | None = None
    action: str
    strength: str
    horizon: str | None = None
    reasoning: str | None = None
    risk_note: str | None = None
    confidence: float = 0.8
    evidence: str | None = None
    raw_content: str

    @model_validator(mode="after")
    def _fill_derived_fields(self) -> Recommendation:
        if not self.target_name:
            self.target_name = self.ticker
        if not self.raw_action:
            self.raw_action = self.action
        if not self.normalized_action:
            self.normalized_action = self.action
        return self


class OpinionNode(BaseModel):
    opinion_id: str
    version: int
    message_id: str
    sender: str
    topic_key: str
    stance: str
    update_type: str
    previous_id: str | None = None
    summary: str
    confidence: float = 0.8
    candidate_existing_topic: str | None = None


# -- config models --


class APIConfig(BaseModel):
    base_url: str = "https://example.com/api"
    sources: list[str] = ["个人消息", "个人群"]
    timeout: int = 30


class LLMProviderConfig(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    api: Literal["openai", "openai-completions", "anthropic-messages"] = "openai"
    headers: dict[str, str] = Field(default_factory=dict)
    max_tokens: int | None = None
    temperature: float = 0.1
    timeout: float = 300.0


class LLMConfig(BaseModel):
    default_provider: str = ""
    providers: dict[str, LLMProviderConfig] = {}
    task_routing: dict[str, str] = {}
    provider_pools: dict[str, list[str]] = Field(default_factory=dict)


class StorageConfig(BaseModel):
    data_dir: str = "~/.config/stock-news/data"
    format: str = "json"


class MarketConfig(BaseModel):
    tushare_api_url: str = ""


class ScheduleConfig(BaseModel):
    pid_file: str = "~/.config/stock-news/scheduler.pid"
    log_dir: str = "~/.config/stock-news/logs"


class DeliveryProviderConfig(BaseModel):
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
    targets: list[str] = Field(default_factory=list)
    format: Literal["text", "post", "markdown", "markdown_v2"] = "post"
    fail_fast: bool = False


class DeliveryConfig(BaseModel):
    providers: dict[str, DeliveryProviderConfig] = Field(default_factory=dict)
    targets: dict[str, DeliveryTargetConfig] = Field(default_factory=dict)
    routes: dict[str, DeliveryRouteConfig] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    sender_whitelist: list[str] = Field(default_factory=list)
    sender_min_count: int = 3
    sender_min_win_rate: float = 0.5


class NightlyPublishConfig(BaseModel):
    host: str = ""
    user: str = ""
    password: str | None = None
    port: int = 22
    remote_dir: str = "/var/www/stock-news"
    url_prefix: str = ""
    sshpass_path: str = "sshpass"


class PublishConfig(BaseModel):
    nightly: NightlyPublishConfig = NightlyPublishConfig()


class AppConfig(BaseModel):
    api: APIConfig = APIConfig()
    llm: LLMConfig = LLMConfig()
    storage: StorageConfig = StorageConfig()
    market: MarketConfig = MarketConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    strategy: StrategyConfig = StrategyConfig()
    publish: PublishConfig = PublishConfig()
