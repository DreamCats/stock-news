"""源头抽取产物存储."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from stock_news.source.models import SourceExtractItem


def source_extract_dir(cfg_data_dir: str, dt: date) -> Path:
    d = Path(cfg_data_dir).expanduser() / dt.isoformat() / "source_extract"
    d.mkdir(parents=True, exist_ok=True)
    return d


def candidates_path(cfg_data_dir: str, dt: date) -> Path:
    return source_extract_dir(cfg_data_dir, dt) / "candidates.json"


def source_scan_dir(cfg_data_dir: str, dt: date) -> Path:
    d = Path(cfg_data_dir).expanduser() / dt.isoformat() / "source_scan"
    d.mkdir(parents=True, exist_ok=True)
    return d


def radar_markdown_path(cfg_data_dir: str, dt: date) -> Path:
    return source_scan_dir(cfg_data_dir, dt) / "radar.md"


def processed_ids_path(cfg_data_dir: str, dt: date) -> Path:
    return source_extract_dir(cfg_data_dir, dt) / "processed_ids.json"


def load_source_extracts(cfg_data_dir: str, dt: date) -> list[SourceExtractItem]:
    path = candidates_path(cfg_data_dir, dt)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SourceExtractItem.model_validate(item) for item in data]


def load_processed_ids(cfg_data_dir: str, dt: date) -> set[str]:
    path = processed_ids_path(cfg_data_dir, dt)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def save_source_extracts(
    cfg_data_dir: str,
    dt: date,
    items: list[SourceExtractItem],
    processed_ids: set[str],
) -> None:
    candidates_path(cfg_data_dir, dt).write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in items],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    processed_ids_path(cfg_data_dir, dt).write_text(
        json.dumps(sorted(processed_ids), ensure_ascii=False),
        encoding="utf-8",
    )
