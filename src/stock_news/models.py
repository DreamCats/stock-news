"""共享数据模型."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, computed_field


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
    ticker: str
    market: str | None = None
    action: str
    strength: str
    horizon: str | None = None
    reasoning: str | None = None
    risk_note: str | None = None
    raw_content: str


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


# -- config models --


class APIConfig(BaseModel):
    base_url: str = "https://example.com/api"
    sources: list[str] = ["个人消息", "个人群"]
    timeout: int = 30


class LLMProviderConfig(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    max_tokens: int | None = None
    temperature: float = 0.1


class LLMConfig(BaseModel):
    default_provider: str = ""
    providers: dict[str, LLMProviderConfig] = {}
    task_routing: dict[str, str] = {}


class StorageConfig(BaseModel):
    data_dir: str = "~/.config/stock-news/data"
    format: str = "json"


class ScheduleConfig(BaseModel):
    pid_file: str = "~/.config/stock-news/scheduler.pid"
    log_dir: str = "~/.config/stock-news/logs"


class AppConfig(BaseModel):
    api: APIConfig = APIConfig()
    llm: LLMConfig = LLMConfig()
    storage: StorageConfig = StorageConfig()
    schedule: ScheduleConfig = ScheduleConfig()
