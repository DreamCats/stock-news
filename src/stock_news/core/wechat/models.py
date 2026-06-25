"""微信原始消息和时间窗口模型。

这些模型只描述数据源拉取结果，不承载分析、分类或投递语义。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class TimeWindow(BaseModel):
    """一个左闭右开的微信拉取时间窗口。"""

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _validate_order(self) -> TimeWindow:
        if self.start >= self.end:
            raise ValueError("时间窗口 start 必须早于 end")
        return self


class WechatMessage(BaseModel):
    """从微信数据源拉到的一条原始消息。"""

    source: str
    sender: str
    message_time: datetime
    content: str
    group_name: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)
    message_id: str = ""

    @model_validator(mode="after")
    def _fill_message_id(self) -> WechatMessage:
        if not self.message_id:
            self.message_id = stable_message_id(
                source=self.source,
                sender=self.sender,
                message_time=self.message_time,
                group_name=self.group_name,
                content=self.content,
            )
        return self


def stable_message_id(
    *,
    source: str,
    sender: str,
    message_time: datetime,
    group_name: str | None,
    content: str,
) -> str:
    """生成跨运行稳定的消息 ID。"""

    key = "\0".join(
        [
            source,
            sender,
            message_time.isoformat(),
            group_name or "",
            content,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
