"""推荐回测增量刷新."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Any

from stock_news.backtest import engine, storage
from stock_news.backtest.constants import CHECKPOINT_EVERY_REFRESHED

ProgressCallback = Callable[[str], None]


def refresh_one_day(
    cfg_data_dir: str,
    dt: date,
    as_of: date,
    ticker_cache: dict[str, str | None],
    mature_cache: dict[date, list[int]],
    *,
    progress: ProgressCallback | None = None,
    label: str | None = None,
    checkpoint_every: int = CHECKPOINT_EVERY_REFRESHED,
) -> dict[str, Any]:
    recs = storage.load_recommendations(cfg_data_dir, dt)
    stats: dict[str, Any] = {
        "date": dt.isoformat(),
        "recommendations": len(recs),
        "refreshed": 0,
        "skipped_complete": 0,
        "pending": 0,
        "unmatched": 0,
        "changed": False,
    }
    if not recs:
        if progress and label:
            progress(f"{label} {dt.isoformat()} 无推荐数据，跳过")
        return stats

    existing = storage.load_backtest_results(cfg_data_dir, dt)
    by_key = {storage.result_key_from_result(item): item for item in existing}
    backtest_cache: dict[tuple[str, str, str, str], dict[str, Any] | None] = {}
    last_progress_at = time.monotonic()

    def save_current_results() -> None:
        storage.save_backtest_results(
            cfg_data_dir,
            dt,
            sorted(
                by_key.values(),
                key=lambda item: (
                    str(item.get("message_id", "")),
                    str(item.get("ticker", "")),
                    str(item.get("action", "")),
                ),
            ),
        )

    if progress and label:
        progress(f"{label} {dt.isoformat()} 推荐 {len(recs)} 条")

    for index, rec in enumerate(recs, start=1):
        rec_dt = rec.message_time.date() if rec.message_time else dt
        mature = mature_cache.get(rec_dt)
        if mature is None:
            mature = engine.mature_windows(rec_dt, as_of)
            mature_cache[rec_dt] = mature
        if not mature:
            stats["pending"] += 1
            last_progress_at = _emit_refresh_progress(
                index,
                len(recs),
                stats,
                progress,
                last_progress_at,
            )
            continue

        key = storage.result_key_from_rec(rec)
        legacy_keys = [
            ("message_id", rec.message_id),
            storage.legacy_result_key_from_rec(rec),
        ]
        old = by_key.get(key)
        if old is None:
            old = next((by_key[k] for k in legacy_keys if k in by_key), None)
        missing = [
            window for window in mature if not old or f"ret_t{window}" not in old
        ]
        if not missing:
            stats["skipped_complete"] += 1
            last_progress_at = _emit_refresh_progress(
                index,
                len(recs),
                stats,
                progress,
                last_progress_at,
            )
            continue

        if rec.ticker not in ticker_cache:
            ticker_cache[rec.ticker] = engine.resolve_ticker(rec.ticker)
        ts_code = ticker_cache[rec.ticker]
        if not ts_code:
            stats["unmatched"] += 1
            last_progress_at = _emit_refresh_progress(
                index,
                len(recs),
                stats,
                progress,
                last_progress_at,
            )
            continue

        rec_date = (
            rec.message_time.strftime("%Y%m%d")
            if rec.message_time
            else dt.strftime("%Y%m%d")
        )
        cache_key = (ts_code, rec_date, rec.action, as_of.isoformat())
        if cache_key not in backtest_cache:
            backtest_cache[cache_key] = engine.backtest_one(
                rec,
                ts_code,
                rec_date,
                as_of=as_of,
            )

        cached_result = backtest_cache[cache_key]
        if cached_result:
            result = storage.result_with_rec_identity(
                cached_result,
                rec,
                ts_code,
                rec_date,
            )
            for legacy_key in legacy_keys:
                by_key.pop(legacy_key, None)
            by_key[key] = result
            stats["refreshed"] += 1
            stats["changed"] = True
            if stats["refreshed"] % checkpoint_every == 0:
                save_current_results()

        last_progress_at = _emit_refresh_progress(
            index,
            len(recs),
            stats,
            progress,
            last_progress_at,
        )

    if stats["changed"]:
        save_current_results()

    if progress:
        progress(
            "  完成: "
            f"更新 {stats['refreshed']}，完整跳过 {stats['skipped_complete']}，"
            f"未成熟 {stats['pending']}，未匹配 {stats['unmatched']}"
        )
    return stats


def _emit_refresh_progress(
    done: int,
    total: int,
    stats: dict[str, Any],
    progress: ProgressCallback | None,
    last_progress_at: float,
) -> float:
    if progress is None:
        return last_progress_at

    now = time.monotonic()
    if done < total and done % 500 != 0 and now - last_progress_at < 10:
        return last_progress_at

    progress(
        "  进度: "
        f"{done}/{total}，更新 {stats['refreshed']}，"
        f"完整跳过 {stats['skipped_complete']}，"
        f"未成熟 {stats['pending']}，未匹配 {stats['unmatched']}"
    )
    return now
