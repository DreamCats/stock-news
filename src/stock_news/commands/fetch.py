"""数据采集命令."""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import click

from stock_news.common.config import load
from stock_news.common.storage import (
    load_fetch_manifest,
    save_fetch_manifest,
    save_messages,
)
from stock_news.common.wechat_api import fetch_messages
from stock_news.models import RawMessage

TIME_FMT = "%Y%m%d%H%M%S"
SAFETY_MARGIN = timedelta(minutes=5)


def _parse_last(last: str) -> tuple[str, str]:
    """解析 --last 参数，如 30m / 2h，返回 (start, end) 时间字符串."""
    m = re.match(r"^(\d+)([mh])$", last)
    if not m:
        raise click.ClickException("--last 格式错误，示例: 30m, 2h")
    amount = int(m.group(1))
    unit = m.group(2)
    now = datetime.now()
    if unit == "m":
        start = now - timedelta(minutes=amount)
    else:
        start = now - timedelta(hours=amount)
    return start.strftime(TIME_FMT), now.strftime(TIME_FMT)


def _parse_date_spec(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError as exc:
            raise click.ClickException(
                "--date 格式错误，示例: today, yesterday, 2026-05-25, 20260525"
            ) from exc


def _parse_time(time_str: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(time_str, "%H:%M")
    except ValueError as exc:
        raise click.ClickException("--time-range 格式错误，示例: 09:00-23:00") from exc
    return parsed.hour, parsed.minute


def _parse_date_time_range(date_str: str, time_range: str) -> tuple[str, str]:
    parts = time_range.split("-", 1)
    if len(parts) != 2:
        raise click.ClickException("--time-range 格式错误，示例: 09:00-23:00")
    dt = _parse_date_spec(date_str)
    start_hour, start_minute = _parse_time(parts[0])
    end_hour, end_minute = _parse_time(parts[1])
    start_dt = datetime.combine(dt, datetime.min.time()).replace(
        hour=start_hour,
        minute=start_minute,
    )
    end_dt = datetime.combine(dt, datetime.min.time()).replace(
        hour=end_hour,
        minute=end_minute,
    )
    if end_dt <= start_dt:
        raise click.ClickException("--time-range 结束时间必须晚于开始时间")
    return start_dt.strftime(TIME_FMT), end_dt.strftime(TIME_FMT)


def resolve_fetch_window(
    start: str | None,
    end: str | None,
    last: str | None,
    date_str: str | None,
    time_range: str | None,
) -> tuple[str, str]:
    """解析 fetch 时间窗口，返回 yyyyMMddHHmmss 字符串."""
    explicit_start_end = bool(start or end)
    explicit_daily_window = bool(date_str or time_range)
    selected = sum(bool(x) for x in (last, explicit_start_end, explicit_daily_window))
    if selected != 1:
        raise click.ClickException(
            "需要且只能指定一种时间窗口: --start/--end, --last, 或 --date/--time-range"
        )

    if last:
        return _parse_last(last)
    if explicit_start_end:
        if not start or not end:
            raise click.ClickException("--start 和 --end 必须同时指定")
        return start, end
    if not date_str or not time_range:
        raise click.ClickException("--date 和 --time-range 必须同时指定")
    return _parse_date_time_range(date_str, time_range)


def _slice_window(
    start_dt: datetime, end_dt: datetime, slice_hours: int
) -> list[tuple[datetime, datetime]]:
    """把 [start, end] 切成多个左闭右闭的子窗口。

    切片边界对齐 slice_hours 整点，最后一个切片可能不足 slice_hours。
    """
    if slice_hours <= 0 or end_dt - start_dt <= timedelta(hours=slice_hours):
        return [(start_dt, end_dt)]

    slices: list[tuple[datetime, datetime]] = []
    cur = start_dt
    while cur <= end_dt:
        next_aligned = (cur + timedelta(hours=slice_hours)).replace(
            minute=0, second=0, microsecond=0
        )
        slice_end = min(next_aligned - timedelta(seconds=1), end_dt)
        slices.append((cur, slice_end))
        cur = slice_end + timedelta(seconds=1)
    return slices


def _is_safely_past(slice_end: datetime, now: datetime) -> bool:
    """slice_end 是否已经过去 SAFETY_MARGIN，可视为"不会再有新消息晚到"。"""
    return slice_end + SAFETY_MARGIN < now


def run_fetch(
    source: str,
    start: str | None,
    end: str | None,
    last: str | None,
    date_str: str | None,
    time_range: str | None,
    json_output: bool,
    slice_hours: int = 1,
    workers: int = 4,
    refresh: bool = False,
) -> None:
    cfg = load()

    start, end = resolve_fetch_window(start, end, last, date_str, time_range)

    sources = cfg.api.sources if source == "all" else [source]
    start_dt = datetime.strptime(start, TIME_FMT)
    end_dt = datetime.strptime(end, TIME_FMT)
    slices = _slice_window(start_dt, end_dt, slice_hours)
    now = datetime.now()

    # 收集窗口涉及的所有日期 → 各加载缓存清单
    dates_in_window: set[date] = set()
    for s, e in slices:
        dates_in_window.add(s.date())
    manifests: dict[date, dict[str, set[tuple[str, str]]]] = {
        dt: load_fetch_manifest(cfg.storage.data_dir, dt) for dt in dates_in_window
    }

    def _is_cached(src: str, s: datetime, e: datetime) -> bool:
        if refresh:
            return False
        if not _is_safely_past(e, now):
            return False
        pair = (s.strftime(TIME_FMT), e.strftime(TIME_FMT))
        return pair in manifests.get(s.date(), {}).get(src, set())

    jobs: list[tuple[str, datetime, datetime]] = []
    cached_count = 0
    for src in sources:
        for s, e in slices:
            if _is_cached(src, s, e):
                cached_count += 1
            else:
                jobs.append((src, s, e))

    def _job(
        src: str, s: datetime, e: datetime
    ) -> tuple[str, datetime, datetime, list[RawMessage], str | None]:
        ss, ee = s.strftime(TIME_FMT), e.strftime(TIME_FMT)
        last_err: str | None = None
        for _ in range(2):  # 一次失败重试一次
            try:
                msgs = fetch_messages(cfg.api.base_url, src, ss, ee, cfg.api.timeout)
                return src, s, e, msgs, None
            except Exception as ex:
                last_err = str(ex)
        return src, s, e, [], last_err

    # source → {message_id: RawMessage}，内存层先去重，防切片边界 / 服务端模糊匹配重复
    collected: dict[str, dict[str, RawMessage]] = {src: {} for src in sources}
    errors: list[dict[str, str]] = []
    total_jobs = len(jobs)
    done = 0

    if jobs:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futures = [ex.submit(_job, *j) for j in jobs]
            for fut in as_completed(futures):
                src, s, e, msgs, err = fut.result()
                done += 1
                if err:
                    errors.append(
                        {
                            "source": src,
                            "window": f"{s.strftime(TIME_FMT)}-{e.strftime(TIME_FMT)}",
                            "error": err,
                        }
                    )
                else:
                    bucket = collected[src]
                    for m in msgs:
                        bucket[m.message_id] = m
                    # 只缓存"已经安全过去"的切片，避免今天最末尾切片漏抓新消息
                    if _is_safely_past(e, now):
                        ss, ee = s.strftime(TIME_FMT), e.strftime(TIME_FMT)
                        manifests.setdefault(s.date(), {}).setdefault(src, set()).add(
                            (ss, ee)
                        )
                if not json_output:
                    tag = "✗" if err else "✓"
                    sys.stderr.write(
                        f"  {tag} [{src}] {s.strftime('%H:%M')}-{e.strftime('%H:%M')} "
                        f"→ {len(msgs)} 条  ({done}/{total_jobs})\n"
                    )
                    sys.stderr.flush()

    # 持久化所有更新过的清单
    for dt, manifest in manifests.items():
        if manifest:
            save_fetch_manifest(cfg.storage.data_dir, dt, manifest)

    total_new = 0
    total_skipped = 0
    results: list[dict[str, object]] = []

    for src in sources:
        msgs = list(collected[src].values())
        new, skipped = save_messages(msgs, cfg.storage.data_dir, src, start, end)
        total_new += new
        total_skipped += skipped
        results.append(
            {
                "source": src,
                "fetched": len(msgs),
                "new": new,
                "skipped": skipped,
            }
        )

    if json_output:
        payload: dict[str, object] = {
            "ok": not errors,
            "data": {
                "window": {"start": start, "end": end},
                "slices": len(slices),
                "slices_cached": cached_count,
                "workers": workers,
                "refresh": refresh,
                "sources": results,
                "total_new": total_new,
                "total_skipped": total_skipped,
            },
            "message": f"采集完成，新增 {total_new} 条，跳过重复 {total_skipped} 条",
        }
        if errors:
            payload["errors"] = errors
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in results:
            click.echo(
                f"  {r['source']}: 拉取 {r['fetched']} 条，"
                f"新增 {r['new']}，跳过重复 {r['skipped']}"
            )
        cache_hint = f"，缓存命中 {cached_count}" if cached_count else ""
        refresh_hint = "，--refresh" if refresh else ""
        click.echo(
            f"合计新增 {total_new} 条，跳过重复 {total_skipped} 条"
            f"（切片 {len(slices)}{cache_hint}，并发 {workers}{refresh_hint}）"
        )
        if errors:
            click.secho(
                f"  ⚠ {len(errors)} 个切片失败，可重跑同窗口补齐：",
                fg="yellow",
                err=True,
            )
            for item in errors[:5]:
                click.secho(
                    f"    [{item['source']}] {item['window']} → {item['error']}",
                    fg="yellow",
                    err=True,
                )
            if len(errors) > 5:
                click.secho(
                    f"    ...（共 {len(errors)} 条，详见 --json 输出）",
                    fg="yellow",
                    err=True,
                )
