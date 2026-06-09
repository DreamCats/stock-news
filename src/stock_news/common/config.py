"""YAML 配置读写."""

from __future__ import annotations

from pathlib import Path

import yaml

from stock_news.models import AppConfig

CONFIG_DIR = Path.home() / ".config" / "stock-news"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    text = CONFIG_FILE.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    return AppConfig.model_validate(data)


def save(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json")
    CONFIG_FILE.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    CONFIG_FILE.chmod(0o600)


def set_nested(cfg: AppConfig, key: str, value: str) -> AppConfig:
    """通过点号路径设置配置项，如 api.timeout -> cfg.api.timeout."""
    data = cfg.model_dump(mode="json")
    parts = key.split(".")
    target = data
    for part in parts[:-1]:
        if part not in target or not isinstance(target[part], dict):
            target[part] = {}
        target = target[part]

    old_value = target.get(parts[-1])
    if isinstance(old_value, int):
        target[parts[-1]] = int(value)
    elif isinstance(old_value, float):
        target[parts[-1]] = float(value)
    elif isinstance(old_value, bool):
        target[parts[-1]] = value.lower() in ("true", "1", "yes")
    elif isinstance(old_value, list):
        import json as json_mod

        target[parts[-1]] = json_mod.loads(value)
    elif old_value is None:
        target[parts[-1]] = value or None
    else:
        target[parts[-1]] = value

    return AppConfig.model_validate(data)
