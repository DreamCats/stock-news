"""策略快报文件读写."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stock_news.models import OpinionNode


def _date_dir(data_dir: str, dt_str: str) -> Path:
    return Path(data_dir).expanduser() / dt_str


def _strategy_dir(data_dir: str, dt_str: str) -> Path:
    d = _date_dir(data_dir, dt_str) / "strategy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_opinions(data_dir: str, dt_str: str) -> list[OpinionNode]:
    path = _date_dir(data_dir, dt_str) / "opinions" / "opinions.json"
    data = _load_json(path, [])
    if not isinstance(data, list):
        return []
    return [OpinionNode.model_validate(item) for item in data]


def _load_sender_stats(data_dir: str) -> dict[str, dict[str, Any]]:
    path = Path(data_dir).expanduser() / "backtest_summary" / "sender_stats.json"
    data = _load_json(path, [])
    if not isinstance(data, list):
        return {}
    return {
        str(item.get("sender")): item
        for item in data
        if isinstance(item, dict) and item.get("sender")
    }


def _load_sender_win_samples(
    data_dir: str,
    senders: set[str],
    limit: int = 3,
) -> dict[str, list[str]]:
    if not senders:
        return {}
    samples: dict[str, list[str]] = {sender: [] for sender in senders}
    seen: dict[str, set[str]] = {sender: set() for sender in senders}
    data_root = Path(data_dir).expanduser()
    if not data_root.exists():
        return samples

    for date_dir in sorted(data_root.iterdir(), reverse=True):
        if all(len(items) >= limit for items in samples.values()):
            break
        if not date_dir.is_dir():
            continue
        results_path = date_dir / "backtest" / "results.json"
        if not results_path.exists():
            continue
        items = _load_json(results_path, [])
        if not isinstance(items, list):
            continue
        for item in reversed(items):
            if not isinstance(item, dict):
                continue
            sender = str(item.get("sender") or "")
            if sender not in senders or len(samples[sender]) >= limit:
                continue
            if item.get("win_t5") is not True:
                continue
            ticker = str(item.get("ticker") or item.get("ts_code") or "").strip()
            if not ticker or ticker in seen[sender]:
                continue
            seen[sender].add(ticker)
            rec_date = str(item.get("rec_date") or date_dir.name)
            suffix = rec_date[5:] if len(rec_date) >= 10 else rec_date
            samples[sender].append(f"{ticker}({suffix})" if suffix else ticker)
    return samples


def _load_state(data_dir: str, dt_str: str) -> dict[str, Any]:
    data = _load_json(_strategy_dir(data_dir, dt_str) / "state.json", {})
    return data if isinstance(data, dict) else {}


def _save_outputs(
    data_dir: str,
    dt_str: str,
    payload: dict[str, Any],
    markdown: str,
    state: dict[str, Any],
) -> tuple[Path, Path]:
    out_dir = _strategy_dir(data_dir, dt_str)
    json_path = out_dir / "strategy.json"
    md_path = out_dir / "strategy.md"
    state_path = out_dir / "state.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path, md_path
