"""配置文件路径规划。

配置按业务域拆分：大多数文件放在 configs/ 目录，
schedule.yaml 仍放在配置根目录，便于后续定时入口直接读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigPaths:
    """stock-news 的配置文件布局。"""

    root_dir: Path
    legacy_file: Path

    @classmethod
    def from_legacy_file(cls, legacy_file: Path) -> ConfigPaths:
        return cls(root_dir=legacy_file.parent, legacy_file=legacy_file)

    @property
    def split_dir(self) -> Path:
        return self.root_dir / "configs"

    @property
    def model_providers_file(self) -> Path:
        return self.split_dir / "models.yaml"

    @property
    def wechat_source_file(self) -> Path:
        return self.split_dir / "wechat.yaml"

    @property
    def tushare_file(self) -> Path:
        return self.split_dir / "tushare.yaml"

    @property
    def channel_file(self) -> Path:
        return self.split_dir / "channel.yaml"

    @property
    def schedule_file(self) -> Path:
        return self.root_dir / "schedule.yaml"
