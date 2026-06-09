"""每日晚报数据模型."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NightlyOutput:
    payload: dict[str, Any]
    json_path: Path
    html_path: Path


@dataclass(frozen=True)
class PublishOutput:
    local_path: Path
    remote_path: str
    url: str
