"""基于 YAML 文件的强类型配置存储。

这里集中处理文件 IO 和模型校验，上层不需要关心配置当前来自 YAML、
环境变量，还是后续的其他后端。
"""

from __future__ import annotations

import json
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel

TConfig = TypeVar("TConfig", bound=BaseModel)


class YAMLConfigStore(Generic[TConfig]):
    """从 YAML 文件读写 pydantic 配置模型。"""

    def __init__(self, path: Path, model_type: type[TConfig]) -> None:
        self.path = path
        self.model_type = model_type

    def load(self, default_factory: Callable[[], TConfig]) -> TConfig:
        if not self.path.exists():
            return default_factory()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"配置文件必须是 YAML object: {self.path}")
        return self.model_type.model_validate(raw)

    def save(self, config: TConfig, *, mode: int | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = config.model_dump(mode="json")
        self.path.write_text(
            yaml.dump(
                data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        if mode is not None:
            self.path.chmod(mode)


def set_nested_value(data: MutableMapping[str, Any], key: str, value: str) -> None:
    """按点号路径设置配置值，并尽量保留原字段类型。"""

    parts = key.split(".")
    target: MutableMapping[str, Any] = data
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child

    leaf = parts[-1]
    old_value = target.get(leaf)
    if isinstance(old_value, bool):
        target[leaf] = value.lower() in ("true", "1", "yes")
    elif isinstance(old_value, int):
        target[leaf] = int(value)
    elif isinstance(old_value, float):
        target[leaf] = float(value)
    elif isinstance(old_value, list):
        target[leaf] = json.loads(value)
    elif old_value is None:
        target[leaf] = value or None
    else:
        target[leaf] = value
