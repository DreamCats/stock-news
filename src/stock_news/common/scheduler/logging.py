"""scheduler JSONL 日志写入与轮转."""

from __future__ import annotations

import json
from pathlib import Path

LOG_ROTATE_BACKUPS = 5
LOG_ROTATE_BYTES = 5 * 1024 * 1024


def _archive_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def rotate_log_if_needed(
    path: Path,
    *,
    max_bytes: int = LOG_ROTATE_BYTES,
    backups: int = LOG_ROTATE_BACKUPS,
) -> bool:
    """当日志超过阈值时轮转为 .1/.2/...，返回是否发生轮转."""
    if max_bytes <= 0 or backups <= 0 or not path.exists():
        return False
    if path.stat().st_size < max_bytes:
        return False

    oldest = _archive_path(path, backups)
    if oldest.exists():
        oldest.unlink()
    for index in range(backups - 1, 0, -1):
        archived = _archive_path(path, index)
        if archived.exists():
            archived.replace(_archive_path(path, index + 1))
    path.replace(_archive_path(path, 1))
    return True


def append_jsonl(
    path: Path,
    event: dict[str, object],
    *,
    max_bytes: int = LOG_ROTATE_BYTES,
    backups: int = LOG_ROTATE_BACKUPS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log_if_needed(path, max_bytes=max_bytes, backups=backups)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_last_log_event(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    last_line = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    if last_line is None:
        return None
    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
