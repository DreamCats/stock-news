"""盘中 workflow 编排."""

from __future__ import annotations

import io
import json
import time
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from stock_news.commands.analyze._common import parse_date
from stock_news.commands.analyze.classify import classify
from stock_news.commands.analyze.extract import extract
from stock_news.commands.analyze.opinion import opinion
from stock_news.commands.backtest import run_backtest_summary
from stock_news.commands.fetch import run_fetch
from stock_news.commands.strategy import generate as strategy_generate
from stock_news.common.config import load
from stock_news.common.delivery.feishu_bot import DeliveryMessage
from stock_news.common.delivery.service import (
    result_payload,
    route_targets,
    send_targets,
)

StepFn = Callable[[], None]
Step = tuple[str, StepFn, bool]


def _workflow_dir(data_dir: str, date_str: str, create: bool = True) -> Path:
    path = Path(data_dir).expanduser() / date_str / "workflow"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _strategy_paths(data_dir: str, date_str: str) -> tuple[Path, Path]:
    base = Path(data_dir).expanduser() / date_str / "strategy"
    return base / "strategy.json", base / "strategy.md"


def _run_step(step: StepFn, capture_output: bool) -> str:
    if not capture_output:
        step()
        return ""

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        step()
    return (out.getvalue() + err.getvalue()).strip()


def _save_last_run(data_dir: str, date_str: str, payload: dict[str, Any]) -> Path:
    path = _workflow_dir(data_dir, date_str) / "last_run.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _load_strategy_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _delivery_step(
    target_name: str | None,
    route_name: str | None,
    markdown_path: Path,
    title: str,
) -> dict[str, Any]:
    if not markdown_path.exists():
        raise click.ClickException(f"策略 Markdown 不存在: {markdown_path}")

    if target_name:
        targets = [target_name]
        fail_fast = False
    else:
        assert route_name is not None
        route, targets = route_targets(route_name)
        fail_fast = route.fail_fast

    message = DeliveryMessage(
        format="markdown",
        text=markdown_path.read_text(encoding="utf-8"),
        title=title,
    )
    results = send_targets(targets, message, fail_fast=fail_fast)
    return result_payload(results)


def _dry_run_payload(
    date_str: str,
    window_minutes: int,
    window_days: int,
    source: str,
    strategy_llm: bool,
    delivery_target: str | None,
    delivery_route: str | None,
) -> dict[str, Any]:
    steps = [
        f"fetch --source {source} --last {window_minutes}m",
        f"analyze classify --date {date_str}",
        f"analyze extract --date {date_str}",
        f"analyze opinion --date {date_str}",
        f"analyze backtest summary --window-days {window_days}",
        (
            f"strategy generate --date {date_str} --window-minutes {window_minutes}"
            + (" --with-llm" if strategy_llm else "")
        ),
    ]
    if delivery_target:
        steps.append(
            f"delivery send --target {delivery_target} --markdown-file strategy.md"
        )
    elif delivery_route:
        steps.append(
            f"delivery send --route {delivery_route} --markdown-file strategy.md"
        )

    return {
        "ok": True,
        "dry_run": True,
        "date": date_str,
        "window_minutes": window_minutes,
        "window_days": window_days,
        "steps": steps,
    }


def run_workflow(
    date_str: str,
    window_minutes: int,
    window_days: int,
    source: str,
    provider_name: str | None,
    delivery_target: str | None,
    delivery_route: str | None,
    send_empty: bool,
    top: int,
    min_count: int,
    slice_hours: int,
    workers: int,
    strategy_llm: bool,
    execute: bool,
    json_output: bool,
) -> None:
    """执行一次盘中 workflow."""
    if delivery_target and delivery_route:
        raise click.ClickException("--delivery-target 和 --delivery-route 只能指定一个")

    cfg = load()
    dt = parse_date(date_str)
    normalized_date = dt.isoformat()

    if not execute:
        payload = _dry_run_payload(
            normalized_date,
            window_minutes,
            window_days,
            source,
            strategy_llm,
            delivery_target,
            delivery_route,
        )
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"workflow dry-run: {normalized_date}")
            for index, step in enumerate(payload["steps"], start=1):
                click.echo(f"  {index}. {step}")
        return

    started_at = datetime.now().replace(microsecond=0)
    started_ts = time.time()
    strategy_json_path, strategy_md_path = _strategy_paths(
        cfg.storage.data_dir,
        normalized_date,
    )
    steps: list[Step] = [
        (
            "fetch",
            lambda: run_fetch(
                source,
                None,
                None,
                f"{window_minutes}m",
                None,
                None,
                False,
                slice_hours,
                workers,
                False,
            ),
            True,
        ),
        (
            "classify",
            lambda: classify(normalized_date, False, provider_name, False),
            True,
        ),
        ("extract", lambda: extract(normalized_date, provider_name, False), True),
        ("opinion", lambda: opinion(normalized_date, provider_name, False), True),
        (
            "backtest_summary",
            lambda: run_backtest_summary(
                False,
                top=top,
                min_count=min_count,
                window_days=window_days,
            ),
            False,
        ),
        (
            "strategy_generate",
            lambda: strategy_generate(
                normalized_date,
                window_minutes,
                top,
                False,
                strategy_llm,
                provider_name,
            ),
            True,
        ),
    ]

    results: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    ok = True
    if not json_output:
        click.echo(f"=== workflow 开始: {normalized_date} ===", err=True)

    for index, (name, step, required) in enumerate(steps, start=1):
        if not json_output:
            click.echo(f"[{index}/{len(steps)}] {name}...", err=True)
        step_started = time.time()
        try:
            output = _run_step(step, capture_output=json_output)
            results.append(
                {
                    "step": name,
                    "ok": True,
                    "required": required,
                    "seconds": round(time.time() - step_started, 2),
                    "output": output[-1000:] if output else "",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "step": name,
                    "ok": False,
                    "required": required,
                    "seconds": round(time.time() - step_started, 2),
                    "error": str(exc),
                }
            )
            if not json_output:
                level = "失败" if required else "警告"
                color = "red" if required else "yellow"
                click.secho(f"  {name} {level}: {exc}", fg=color, err=True)
            if required:
                ok = False
                break
            warnings.append({"step": name, "error": str(exc)})
            continue

    strategy_payload = _load_strategy_payload(strategy_json_path)
    delivery_result: dict[str, Any] | None = None
    should_send = bool(delivery_target or delivery_route)
    has_updates = bool(strategy_payload.get("has_updates"))
    if ok and should_send and (has_updates or send_empty):
        try:
            delivery_result = _delivery_step(
                delivery_target,
                delivery_route,
                strategy_md_path,
                title=f"盘中投研快报 {normalized_date}",
            )
            ok = bool(delivery_result.get("ok"))
        except Exception as exc:
            ok = False
            delivery_result = {"ok": False, "error": str(exc)}

    if not ok:
        status = "failed"
    elif warnings:
        status = "completed_with_warnings"
    else:
        status = "success"
    finished_at = datetime.now().replace(microsecond=0)
    run_payload: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "date": normalized_date,
        "window_minutes": window_minutes,
        "window_days": window_days,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "seconds": round(time.time() - started_ts, 2),
        "steps": results,
        "warnings": warnings,
        "strategy": {
            "has_updates": has_updates,
            "json_path": str(strategy_json_path),
            "markdown_path": str(strategy_md_path),
        },
        "delivery": delivery_result,
    }
    state_path = _save_last_run(cfg.storage.data_dir, normalized_date, run_payload)

    if json_output:
        click.echo(json.dumps(run_payload, ensure_ascii=False, indent=2))
    else:
        label = (
            "失败"
            if status == "failed"
            else "完成（有警告）"
            if status == "completed_with_warnings"
            else "完成"
        )
        click.echo(f"\nworkflow {label}: {normalized_date}")
        click.echo(f"状态已保存: {state_path}")

    if not ok:
        raise click.exceptions.Exit(1)


def workflow_status(date_str: str, json_output: bool) -> None:
    """查看最近一次 workflow 状态."""
    cfg = load()
    dt = parse_date(date_str)
    normalized_date = dt.isoformat()
    path = (
        _workflow_dir(
            cfg.storage.data_dir,
            normalized_date,
            create=False,
        )
        / "last_run.json"
    )
    if not path.exists():
        message = f"{normalized_date} 暂无 workflow 运行记录"
        if json_output:
            click.echo(
                json.dumps(
                    {"ok": True, "data": None, "message": message},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            click.echo(message)
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    if json_output:
        click.echo(json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2))
        return

    status = data.get("status") or ("ok" if data.get("ok") else "failed")
    click.echo(f"{normalized_date} workflow: {status}")
    click.echo(f"started_at: {data.get('started_at')}")
    click.echo(f"finished_at: {data.get('finished_at')}")
    for step in data.get("steps", []):
        if isinstance(step, dict):
            step_status = "ok" if step.get("ok") else f"failed: {step.get('error')}"
            click.echo(f"  {step.get('step')}: {step_status}")
    for warning in data.get("warnings", []):
        if isinstance(warning, dict):
            click.echo(f"  warning {warning.get('step')}: {warning.get('error')}")
