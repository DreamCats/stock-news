"""本地数据存储 + 去重."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from stock_news.models import RawMessage


def _data_dir(cfg_data_dir: str) -> Path:
    return Path(cfg_data_dir).expanduser()


def _date_dir(cfg_data_dir: str, dt: date) -> Path:
    return _data_dir(cfg_data_dir) / dt.isoformat()


def _raw_dir(cfg_data_dir: str, dt: date) -> Path:
    d = _date_dir(cfg_data_dir, dt) / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_existing_ids(raw_dir: Path) -> set[str]:
    """加载已有消息的 ID 集合用于去重."""
    ids: set[str] = set()
    for f in raw_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for msg in data:
                m = RawMessage.model_validate(msg)
                ids.add(m.message_id)
        except Exception:
            continue
    return ids


def _load_file_messages(path: Path) -> list[RawMessage]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [RawMessage.model_validate(item) for item in data]
    except Exception:
        return []


def save_messages(
    messages: list[RawMessage],
    cfg_data_dir: str,
    source: str,
    window_start: str,
    window_end: str,
) -> tuple[int, int]:
    """保存消息并去重，返回 (新增数, 跳过数)."""
    if not messages:
        return 0, 0

    by_date: dict[date, list[RawMessage]] = {}
    for msg in messages:
        by_date.setdefault(msg.message_time.date(), []).append(msg)

    total_new = 0
    total_skipped = 0
    filename = f"{source}_{window_start}_{window_end}.json"

    for dt, date_messages in by_date.items():
        raw_dir = _raw_dir(cfg_data_dir, dt)
        existing_ids = _load_existing_ids(raw_dir)

        new_messages = []
        for msg in date_messages:
            if msg.message_id in existing_ids:
                total_skipped += 1
            else:
                new_messages.append(msg)
                existing_ids.add(msg.message_id)

        if not new_messages:
            continue

        filepath = raw_dir / filename
        merged_messages = _load_file_messages(filepath) + new_messages
        merged_messages.sort(key=lambda msg: msg.message_time)
        total_new += len(new_messages)

        data = [m.model_dump(mode="json") for m in merged_messages]
        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return total_new, total_skipped


def _manifest_path(cfg_data_dir: str, dt: date) -> Path:
    return _raw_dir(cfg_data_dir, dt) / ".fetched.json"


def load_fetch_manifest(cfg_data_dir: str, dt: date) -> dict[str, set[tuple[str, str]]]:
    """加载某日的 fetch 切片缓存清单：source → {(start, end), ...}."""
    p = _manifest_path(cfg_data_dir, dt)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, set[tuple[str, str]]] = {}
    if isinstance(data, dict):
        for src, slices in data.items():
            if not isinstance(slices, list):
                continue
            out[src] = {
                (s[0], s[1]) for s in slices if isinstance(s, list) and len(s) == 2
            }
    return out


def save_fetch_manifest(
    cfg_data_dir: str,
    dt: date,
    manifest: dict[str, set[tuple[str, str]]],
) -> None:
    """落盘某日切片缓存清单。"""
    p = _manifest_path(cfg_data_dir, dt)
    p.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        src: sorted([list(pair) for pair in slices])
        for src, slices in manifest.items()
        if slices
    }
    p.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_messages(
    cfg_data_dir: str,
    dt: date,
    source: str | None = None,
) -> list[RawMessage]:
    """加载指定日期的消息."""
    raw_dir = _date_dir(cfg_data_dir, dt) / "raw"
    if not raw_dir.exists():
        return []

    messages: list[RawMessage] = []
    for f in sorted(raw_dir.glob("*.json")):
        if source and not f.name.startswith(source):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for item in data:
                messages.append(RawMessage.model_validate(item))
        except Exception:
            continue

    return sorted(messages, key=lambda m: m.message_time)


def get_stats(cfg_data_dir: str, dt: date) -> dict[str, object]:
    """获取指定日期的数据统计."""
    messages = load_messages(cfg_data_dir, dt)
    if not messages:
        return {
            "date": dt.isoformat(),
            "total": 0,
            "sources": {},
            "time_range": None,
        }

    source_counts: dict[str, int] = {}
    sender_counts: dict[str, int] = {}
    for m in messages:
        source_counts[m.source] = source_counts.get(m.source, 0) + 1
        sender_counts[m.sender] = sender_counts.get(m.sender, 0) + 1

    return {
        "date": dt.isoformat(),
        "total": len(messages),
        "sources": source_counts,
        "senders_count": len(sender_counts),
        "top_senders": dict(
            sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ),
        "time_range": {
            "start": messages[0].message_time.isoformat(),
            "end": messages[-1].message_time.isoformat(),
        },
    }


def find_duplicates(cfg_data_dir: str, dt: date) -> list[dict[str, str]]:
    """找出指定日期的重复消息."""
    raw_dir = _date_dir(cfg_data_dir, dt) / "raw"
    if not raw_dir.exists():
        return []

    seen: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []

    for f in sorted(raw_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for item in data:
                m = RawMessage.model_validate(item)
                if m.message_id in seen:
                    duplicates.append(
                        {
                            "message_id": m.message_id,
                            "sender": m.sender,
                            "time": m.message_time.isoformat(),
                            "first_file": seen[m.message_id],
                            "dup_file": f.name,
                        }
                    )
                else:
                    seen[m.message_id] = f.name
        except Exception:
            continue

    return duplicates


def dedup_date(cfg_data_dir: str, dt: date, dry_run: bool = False) -> int:
    """去重指定日期的数据，返回删除的重复数."""
    raw_dir = _date_dir(cfg_data_dir, dt) / "raw"
    if not raw_dir.exists():
        return 0

    all_messages: dict[str, tuple[RawMessage, str]] = {}
    dup_count = 0

    files_data: dict[str, list[RawMessage]] = {}
    for f in sorted(raw_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            msgs = [RawMessage.model_validate(item) for item in data]
            files_data[f.name] = msgs
            for m in msgs:
                if m.message_id in all_messages:
                    dup_count += 1
                else:
                    all_messages[m.message_id] = (m, f.name)
        except Exception:
            continue

    if dry_run or dup_count == 0:
        return dup_count

    deduped_by_file: dict[str, list[RawMessage]] = {}
    seen: set[str] = set()
    for fname, msgs in files_data.items():
        unique = []
        for m in msgs:
            if m.message_id not in seen:
                unique.append(m)
                seen.add(m.message_id)
        deduped_by_file[fname] = unique

    for fname, msgs in deduped_by_file.items():
        filepath = raw_dir / fname
        if msgs:
            data = [m.model_dump(mode="json") for m in msgs]
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            filepath.unlink()

    return dup_count
