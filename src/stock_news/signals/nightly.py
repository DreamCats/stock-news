"""每日晚报信号生成."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path
from shlex import quote
from typing import Any

from stock_news.commands.strategy.payload import _build_candidate_trades
from stock_news.commands.strategy.scoring import _build_consensus
from stock_news.commands.strategy.storage import _load_sender_stats
from stock_news.commands.strategy.utils import _rec_time, _target_name
from stock_news.common.config import load
from stock_news.common.llm.task_pool import (
    chunked,
    resolve_provider_pool,
    run_provider_batches,
    select_provider,
)
from stock_news.models import NightlyPublishConfig, Recommendation

_DIMENSION_KEYWORDS = {
    "valuation": ("目标市值", "空间", "PE", "估值", "倍", "亿"),
    "position": ("龙头", "唯一", "份额", "卡位", "供应商", "国产替代", "核心"),
    "catalyst": ("订单", "客户", "涨价", "提价", "交付", "突破", "绑定", "招标"),
    "capacity": ("产能", "扩产", "满负荷", "良率", "毛利", "净利", "业绩", "利润"),
}
_NOISE_WORDS = {
    "重点推荐",
    "重点关注",
    "继续推荐",
    "建议关注",
    "强烈推荐",
    "投资建议",
    "持续坚定推荐",
    "核心推荐",
    "继续坚定推荐",
    "放心买入",
    "送钱机会",
}
_TAG_WORDS = (
    "红包",
    "礼物",
    "玫瑰",
    "太阳",
    "烟花",
    "福",
    "庆祝",
    "强",
    "重点",
)
_NIGHTLY_BATCH_SIZE = 16
_NIGHTLY_BATCH_WORKERS = 2


@dataclass(frozen=True)
class NightlyOutput:
    payload: dict[str, Any]
    json_path: Path
    html_path: Path


@dataclass(frozen=True)
class PublishOutput:
    local_path: Path
    remote_path: str
    url: str


def parse_datetime_expr(value: str, now: datetime | None = None) -> datetime:
    """解析晚报时间表达式."""
    base = now or datetime.now()
    normalized = value.strip()
    for prefix, day in (
        ("today-", base.date()),
        ("yesterday-", base.date() - timedelta(days=1)),
    ):
        if normalized.startswith(prefix):
            clock = _parse_clock(normalized[len(prefix) :])
            return datetime.combine(day, clock)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(
        "时间格式非法，支持 today-21:00、yesterday-15:00、"
        "YYYY-MM-DD HH:MM 或 YYYY-MM-DDTHH:MM"
    )


def generate_nightly_report(
    data_dir: str,
    start: datetime,
    end: datetime,
    top: int = 16,
    *,
    candidate_top: int | None = None,
    use_llm: bool = False,
    provider_name: str | None = None,
    generated_at: datetime | None = None,
    html_out: Path | None = None,
    json_out: Path | None = None,
) -> NightlyOutput:
    """从 recommend 数据生成每日晚报 JSON 和 HTML."""
    if start >= end:
        raise ValueError("开始时间必须早于结束时间")
    if top <= 0:
        raise ValueError("top 必须大于 0")
    candidate_limit = max(candidate_top or top, top)

    recs = _load_recommendations_range(data_dir, start.date(), end.date())
    window_recs = [
        rec
        for rec in recs
        if rec.message_time is not None and start <= rec.message_time <= end
    ]
    stock_recs = [rec for rec in window_recs if (rec.target_type or "stock") == "stock"]
    sender_stats = _load_sender_stats(data_dir)
    consensus_all = _build_consensus(stock_recs, sender_stats, None)
    candidates = _build_candidate_trades(consensus_all, [], candidate_limit)

    payload: dict[str, Any] = {
        "report_type": "nightly",
        "generated_at": (generated_at or datetime.now()).isoformat(timespec="seconds"),
        "window": {
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
        },
        "stats": {
            "recommendations": len(recs),
            "window_recommendations": len(window_recs),
            "window_stock_recommendations": len(stock_recs),
            "candidates": len(candidates),
            "final_items": 0,
        },
        "candidate_trades": candidates,
        "sender_stats": {
            sender: sender_stats[sender]
            for item in candidates
            for sender in item.get("senders", [])
            if sender in sender_stats
        },
    }
    out_dir = Path(data_dir).expanduser() / end.date().isoformat() / "nightly"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload["items"] = _nightly_items(payload, stock_recs)
    _attach_boss_lines(
        payload,
        use_llm,
        provider_name,
        final_top=top,
        batch_dir=out_dir / "llm_batches",
    )
    payload["stats"]["final_items"] = len(payload.get("items") or [])

    json_path = json_out.expanduser() if json_out else out_dir / "nightly.json"
    html_path = html_out.expanduser() if html_out else out_dir / "nightly.html"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    html_path.write_text(render_nightly_html(payload), encoding="utf-8")
    return NightlyOutput(payload=payload, json_path=json_path, html_path=html_path)


def nightly_paths(data_dir: str, dt: date) -> tuple[Path, Path]:
    out_dir = Path(data_dir).expanduser() / dt.isoformat() / "nightly"
    return out_dir / "nightly.json", out_dir / "nightly.html"


def publish_nightly_html(
    local_html: Path,
    dt: date,
    config: NightlyPublishConfig,
) -> PublishOutput:
    """发布晚报 HTML 到静态服务器."""
    if not local_html.exists():
        raise ValueError(f"晚报 HTML 不存在: {local_html}")
    if not config.host or not config.user:
        raise ValueError("请先配置 publish.nightly.host 和 publish.nightly.user")
    if not config.password:
        raise ValueError("请先配置 publish.nightly.password")
    if not config.url_prefix:
        raise ValueError("请先配置 publish.nightly.url_prefix")

    remote_dir = config.remote_dir.rstrip("/")
    remote_month_dir = f"{remote_dir}/{dt:%Y/%m}"
    remote_name = f"nightly-{dt.isoformat()}.html"
    remote_path = f"{remote_month_dir}/{remote_name}"
    ssh_target = f"{config.user}@{config.host}"
    env = os.environ.copy()
    env["SSHPASS"] = config.password
    ssh_opts = [
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]

    _run_publish_cmd(
        [
            config.sshpass_path,
            "-e",
            "ssh",
            *ssh_opts,
            "-p",
            str(config.port),
            ssh_target,
            f"mkdir -p {quote(remote_month_dir)}",
        ],
        env,
    )
    _run_publish_cmd(
        [
            config.sshpass_path,
            "-e",
            "scp",
            *ssh_opts,
            "-P",
            str(config.port),
            str(local_html),
            f"{ssh_target}:{remote_path}",
        ],
        env,
    )
    url = f"{config.url_prefix.rstrip('/')}/{dt:%Y/%m}/{remote_name}"
    return PublishOutput(local_path=local_html, remote_path=remote_path, url=url)


def render_nightly_html(payload: dict[str, Any]) -> str:
    """渲染适合手机扫读的晚报 HTML."""
    window = payload.get("window") or {}
    start = _display_dt(str(window.get("start") or ""))
    end = _display_dt(str(window.get("end") or ""))
    items = payload.get("items") or []
    generated_at = _display_dt(str(payload.get("generated_at") or ""))
    rows = []
    for item in items:
        name = escape(str(item.get("target_name") or "-"))
        brief = escape(str(item.get("brief") or "-"))
        rows.append(
            f"""
            <li>
              <div class="line">
                <span class="dash">-</span><strong>{name}</strong>：{brief}
              </div>
            </li>
            """
        )
    if not rows:
        rows.append('<li><div class="line">本窗口暂无可进入晚报的股票推荐。</div></li>')

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日投研晚报</title>
  <style>
    :root {{
      color: #1f2933;
      background: #f7f8fa;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body {{
      margin: 0;
      background: #f7f8fa;
    }}
    main {{
      max-width: 760px;
      margin: 0 auto;
      padding: 24px 18px 36px;
      background: #ffffff;
      min-height: 100vh;
      box-sizing: border-box;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.25;
    }}
    .sub {{
      margin: 0 0 22px;
      color: #667085;
      font-size: 13px;
      line-height: 1.6;
    }}
    ul {{
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    li {{
      padding: 4px 0;
    }}
    .line {{
      font-size: 18px;
      line-height: 1.48;
      font-weight: 560;
    }}
    .dash {{
      display: inline-block;
      width: 18px;
      font-weight: 700;
    }}
    footer {{
      margin-top: 22px;
      color: #98a2b3;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>每日投研晚报</h1>
    <p class="sub">
      窗口：{escape(start)} - {escape(end)}；生成：{escape(generated_at)}
    </p>
    <ul>
      {"".join(rows)}
    </ul>
    <footer>仅基于本地 recommend 结构化数据生成，不构成投资建议。</footer>
  </main>
</body>
</html>
"""


def _load_recommendations_range(
    data_dir: str,
    start: date,
    end: date,
) -> list[Recommendation]:
    out: list[Recommendation] = []
    root = Path(data_dir).expanduser()
    current = start
    while current <= end:
        path = root / current.isoformat() / "extracted" / "recommendations.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                out.extend(Recommendation.model_validate(item) for item in data)
        current += timedelta(days=1)
    return out


def _nightly_items(
    payload: dict[str, Any],
    recommendations: list[Recommendation],
) -> list[dict[str, Any]]:
    recs_by_target = _group_recommendations_by_target(recommendations)
    target_names = {
        str(candidate.get("target_name") or "")
        for candidate in payload.get("candidate_trades") or []
        if candidate.get("target_name")
    }
    items = []
    for index, candidate in enumerate(payload.get("candidate_trades") or [], start=1):
        senders = [str(sender) for sender in candidate.get("senders", []) if sender]
        target_name = str(candidate.get("target_name") or "")
        target_recs = recs_by_target.get(target_name, [])
        source_fragments = _source_fragments(target_name, target_recs, target_names)
        risks = _risk_fragments(target_recs)
        brief = _template_boss_line(candidate, source_fragments, risks)
        items.append(
            {
                "rank": index,
                "target_name": target_name,
                "ticker": candidate.get("ticker"),
                "score": candidate.get("score"),
                "recommendation_count": len(target_recs),
                "senders": senders,
                "senders_text": "、".join(senders[:5]) or "-",
                "why_selected": candidate.get("why_selected") or [],
                "source_fragments": source_fragments,
                "risks": risks,
                "logic_source": "template",
                "brief": brief,
            }
        )
    return items


def _group_recommendations_by_target(
    recommendations: list[Recommendation],
) -> dict[str, list[Recommendation]]:
    grouped: dict[str, list[Recommendation]] = {}
    for rec in recommendations:
        grouped.setdefault(_target_name(rec), []).append(rec)
    for recs in grouped.values():
        recs.sort(key=lambda rec: _rec_time(rec, datetime.min), reverse=True)
    return grouped


def _source_fragments(
    target_name: str,
    recs: list[Recommendation],
    target_names: set[str],
) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for rec in recs:
        for source_rank, text in enumerate(
            [rec.reasoning, rec.evidence, rec.raw_content],
            start=1,
        ):
            if not text:
                continue
            for sentence in _split_material(str(text)):
                if _is_raw_noise(sentence):
                    continue
                fragment = _clean_fragment(sentence)
                fragment = _normalize_target_fragment(target_name, fragment)
                if not _is_useful_fragment(target_name, fragment, target_names):
                    continue
                raw_score = _fragment_score(target_name, fragment)
                if source_rank == 3:
                    if target_name and target_name not in fragment:
                        continue
                    if raw_score < 3:
                        continue
                candidates.append((raw_score - source_rank, fragment))

    out: list[str] = []
    seen: set[str] = set()
    for _, fragment in sorted(candidates, key=lambda item: item[0], reverse=True):
        normalized = fragment.casefold()
        if normalized in seen:
            continue
        if any(fragment in existing or existing in fragment for existing in out):
            continue
        seen.add(normalized)
        out.append(_clip_text(fragment, max_len=105))
        if len(out) >= 5:
            break
    return out


def _risk_fragments(recs: list[Recommendation]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for rec in recs:
        risk = _clean_fragment(rec.risk_note or "")
        if not risk or risk in seen:
            continue
        seen.add(risk)
        out.append(_clip_text(risk, max_len=70))
        if len(out) >= 2:
            break
    return out


def _template_boss_line(
    candidate: dict[str, Any],
    fragments: list[str],
    risks: list[str],
) -> str:
    if fragments:
        selected = _select_boss_fragments(fragments)
        line = "，".join(selected)
        if risks:
            line = f"{line}；待验证{risks[0]}"
        return _clean_boss_line(line, max_len=135)

    clues = candidate.get("evidences") or candidate.get("reasons") or []
    clue = "，".join(
        _clip_text(_clean_fragment(str(item)), max_len=55) for item in clues[:3] if item
    )
    if clue:
        return _clean_boss_line(clue, max_len=135)
    return "本窗口有新增推荐，但结构化证据不足，需要回看原文验证产业逻辑。"


def _select_boss_fragments(fragments: list[str]) -> list[str]:
    selected: list[str] = []

    for dimension in ("valuation", "position", "catalyst", "capacity"):
        for fragment in fragments:
            if fragment in selected:
                continue
            if _fragment_dimension(fragment) == dimension:
                selected.append(fragment)
                break

    for fragment in fragments:
        if len(selected) >= 3:
            break
        if fragment not in selected:
            selected.append(fragment)

    if not selected and fragments:
        selected.append(fragments[0])
    return selected[:3]


def _fragment_dimension(fragment: str) -> str:
    for dimension, keywords in _DIMENSION_KEYWORDS.items():
        if any(keyword in fragment for keyword in keywords):
            return dimension
    return "other"


def _attach_boss_lines(
    payload: dict[str, Any],
    use_llm: bool,
    provider_name: str | None,
    *,
    final_top: int,
    batch_dir: Path,
) -> None:
    items = payload.get("items") or []
    logic_error = ""
    if not use_llm or not items:
        payload["items"] = items[:final_top]
        payload["logic_generation"] = {
            "enabled": use_llm,
            "source": "template",
            "error": None,
        }
        return

    try:
        cfg = load()
        providers = resolve_provider_pool(cfg, "nightly", provider_name)
        lines_by_name = _generate_boss_lines_in_batches(items, providers, batch_dir)
        if not lines_by_name:
            logic_error = "LLM 未返回可用晚报条目，已降级为本地模板。"
        target_names = {
            str(item.get("target_name") or "")
            for item in items
            if item.get("target_name")
        }
        for item in items:
            target_name = str(item.get("target_name") or "")
            boss_line = lines_by_name.get(target_name)
            if boss_line and _is_valid_boss_line(target_name, boss_line, target_names):
                item["brief"] = _clean_boss_line(boss_line, max_len=135)
                item["logic_source"] = "llm"
        items = _select_final_items(items, providers, final_top, batch_dir)
    except Exception as exc:  # pragma: no cover - depends on external provider
        logic_error = str(exc)

    payload["items"] = items[:final_top]
    payload["logic_generation"] = {
        "enabled": use_llm,
        "source": (
            "llm"
            if any(item.get("logic_source") == "llm" for item in payload["items"])
            else "template"
        ),
        "error": logic_error or None,
        "batch_size": _NIGHTLY_BATCH_SIZE,
        "batch_workers": _NIGHTLY_BATCH_WORKERS,
    }


def _generate_boss_lines_in_batches(
    items: list[dict[str, Any]],
    providers: tuple[str | None, ...],
    batch_dir: Path,
) -> dict[str, str]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    batches = chunked(items, _NIGHTLY_BATCH_SIZE)
    results = run_provider_batches(
        batches,
        providers,
        _NIGHTLY_BATCH_WORKERS,
        _generate_boss_lines_for_batch,
    )

    out: dict[str, str] = {}
    for result in results:
        batch_payload = {
            "batch_index": result.batch_index,
            "provider": result.provider_name,
            "items": result.result,
        }
        (batch_dir / f"batch-{result.batch_index + 1:02d}.json").write_text(
            json.dumps(batch_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        out.update(result.result)
    return out


def _generate_boss_lines_for_batch(
    items: list[dict[str, Any]],
    provider_name: str | None,
) -> dict[str, str]:
    from stock_news.common.llm.client import chat

    llm_items = [
        {
            "target_name": item.get("target_name"),
            "ticker": item.get("ticker"),
            "source_fragments": item.get("source_fragments", [])[:5],
            "risks": item.get("risks", [])[:2],
        }
        for item in items
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是买方投研负责人，负责把推荐原料压缩成老板可扫读的晚报。"
                "只允许使用输入材料，不得补充外部事实或编造数字。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "为每个标的生成一条强逻辑晚报句。",
                    "output_schema": {
                        "items": [
                            {
                                "target_name": "必须与输入一致",
                                "boss_line": (
                                    "45到120字中文；结构类似：空间/目标市值 + "
                                    "产业链位置 + 订单/客户/价格/产能/催化 + 风险边际"
                                ),
                            }
                        ]
                    },
                    "requirements": [
                        "只输出纯 JSON，不要 markdown。",
                        "不要写推荐条数、推荐人共识、score、候选池。",
                        "不要保留表情、手机号、联系人、券商署名、群聊口号。",
                        "不要把其他候选标的的逻辑写进当前标的。",
                        "不要使用省略号，不要输出不完整句子。",
                        "优先保留输入里的数字、比例、金额、时间、客户、订单、涨价、份额、目标市值。",
                        "证据不足时直接写待验证点，不要硬凑确定性。",
                        "每条像截图里的短 bullet，可用逗号和分号串联，"
                        "不要写成解释段落。",
                    ],
                    "items": llm_items,
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = chat(messages, provider_name=provider_name, disable_thinking=True).strip()
    parsed = _parse_llm_json(raw)
    raw_items = parsed.get("items")
    if not isinstance(raw_items, list):
        return {}

    out: dict[str, str] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        target_name = str(
            raw_item.get("target_name") or raw_item.get("name") or ""
        ).strip()
        boss_line = _clean_boss_line(
            str(raw_item.get("boss_line") or raw_item.get("brief") or "").strip(),
            max_len=135,
        )
        if target_name and boss_line:
            out[target_name] = boss_line
    return out


def _select_final_items(
    items: list[dict[str, Any]],
    providers: tuple[str | None, ...],
    final_top: int,
    batch_dir: Path,
) -> list[dict[str, Any]]:
    if len(items) <= final_top:
        return items
    provider = select_provider(providers, 0)
    selected_names = _select_final_names_with_llm(items, provider, final_top)
    selected = []
    seen: set[str] = set()
    by_name = {str(item.get("target_name") or ""): item for item in items}
    for name in selected_names:
        item = by_name.get(name)
        if item is None or name in seen:
            continue
        selected.append(item)
        seen.add(name)
        if len(selected) >= final_top:
            break
    for item in items:
        if len(selected) >= final_top:
            break
        name = str(item.get("target_name") or "")
        if name and name not in seen:
            selected.append(item)
            seen.add(name)

    judge_payload = {
        "provider": provider,
        "final_top": final_top,
        "selected": [item.get("target_name") for item in selected],
    }
    (batch_dir / "final-selection.json").write_text(
        json.dumps(judge_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return selected


def _select_final_names_with_llm(
    items: list[dict[str, Any]],
    provider_name: str | None,
    final_top: int,
) -> list[str]:
    from stock_news.common.llm.client import chat

    judge_items = [
        {
            "target_name": item.get("target_name"),
            "boss_line": item.get("brief"),
            "score": item.get("score"),
            "recommendation_count": item.get("recommendation_count"),
        }
        for item in items
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是买方投研负责人，负责从候选晚报条目中挑出最适合发给老板的条目。"
                "只基于输入，不补充外部事实。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": f"从候选中选出强逻辑 top{final_top}。",
                    "output_schema": {
                        "selected": [
                            {
                                "target_name": "必须与输入一致",
                                "reason": "为什么入选，20字以内",
                            }
                        ]
                    },
                    "criteria": [
                        "优先选择有数字、订单、客户、涨价、份额、目标市值、产业链位置的条目。",
                        "剔除口号化、证据弱、只说受益但没有传导逻辑的条目。",
                        "尽量避免同一主题重复刷屏，除非标的 alpha 明显不同。",
                        "只输出纯 JSON，不要 markdown。",
                    ],
                    "items": judge_items,
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = chat(messages, provider_name=provider_name, disable_thinking=True).strip()
    parsed = _parse_llm_json(raw)
    raw_selected = parsed.get("selected") or parsed.get("items")
    if not isinstance(raw_selected, list):
        return []
    names = []
    for item in raw_selected:
        if isinstance(item, dict):
            name = str(item.get("target_name") or "").strip()
        else:
            name = str(item).strip()
        if name:
            names.append(name)
        if len(names) >= final_top:
            break
    return names


def _parse_llm_json(raw: str) -> dict[str, Any]:
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
    parsed: Any
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start_obj = raw.find("{")
        end_obj = raw.rfind("}")
        start_arr = raw.find("[")
        end_arr = raw.rfind("]")
        if (
            start_arr != -1
            and end_arr > start_arr
            and (start_obj == -1 or start_arr < start_obj)
        ):
            snippet = raw[start_arr : end_arr + 1]
        elif start_obj != -1 and end_obj > start_obj:
            snippet = raw[start_obj : end_obj + 1]
        else:
            return {}
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            return {}
    if isinstance(parsed, list):
        return {"items": parsed}
    if isinstance(parsed, dict):
        items = parsed.get("items") or parsed.get("data") or parsed.get("result")
        if isinstance(items, list):
            return {"items": items}
        return parsed
    return {}


def _split_material(text: str) -> list[str]:
    compact = re.sub(r"[ \t]+", " ", text.replace("\r", "\n"))
    parts = re.split(r"[\n。！？!?；;]+", compact)
    return [part.strip(" -—:：,，[]【】（）()") for part in parts if part.strip()]


def _clean_fragment(text: str) -> str:
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"[0-9][\ufe0f]?\u20e3", "", text)
    text = re.sub(r"1[3-9]\d{9}", "", text)
    text = re.sub(r"\b\d{3,4}[- ]?\d{7,8}\b", "", text)
    for tag in _TAG_WORDS:
        text = text.replace(f"[{tag}]", "")
        text = text.replace(f"【{tag}】", "")
        text = text.replace(f"{tag}]", "")
    for word in _NOISE_WORDS:
        text = text.replace(word, "")
    text = re.sub(r"^[A-Za-z0-9]{2,12}】", "", text)
    text = re.sub(r"【[A-Za-z][^】]{0,24}$", "", text)
    text = re.sub(r"\b[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}$", "", text)
    text = re.sub(r"东北通信】|东吴电子】|长江电子/建材】", "", text)
    text = re.sub(r"材料[0-9一二三四五六七八九十]+[-—]", "", text)
    text = re.sub(r"^#+", "", text)
    text = text.replace("#", "")
    text = re.sub(r"^[0-9一二三四五六七八九十]+[、.．)]", "", text)
    text = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]+", "", text)
    text = text.replace("...", "，").replace("…", "，")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -—:：,，[]【】（）()")


def _normalize_target_fragment(target_name: str, fragment: str) -> str:
    if target_name:
        fragment = re.sub(
            rf"^[【\[]?{re.escape(target_name)}[】\]]?[：:，, ]*",
            "",
            fragment,
        )
        fragment = re.sub(
            rf"^[^，,：:；;]{{0,36}}[【\[]?{re.escape(target_name)}[】\]]?[：:]",
            "",
            fragment,
        )
    return fragment.strip(" -—:：,，[]【】（）()")


def _is_raw_noise(text: str) -> bool:
    noise_patterns = [
        r"一篮子标的",
        r"其他.{0,8}标的",
        r"弹性角度",
        r"线上交流",
        r"会议",
        r"电话会",
        r"联系人",
        r"郭威秀",
        r"Rogelio",
        r"强call",
        r"强推",
        r"放心买入",
        r"送钱机会",
        r"蠢蠢欲动",
        r"重点更新",
        r"核心推荐的",
    ]
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in noise_patterns):
        return True
    return False


def _is_useful_fragment(
    target_name: str,
    fragment: str,
    target_names: set[str],
) -> bool:
    if len(fragment) < 6 or len(fragment) > 160:
        return False
    if fragment == target_name:
        return False
    if fragment in _NOISE_WORDS:
        return False
    if _contains_contact_noise(fragment):
        return False
    if _other_target_count(target_name, fragment, target_names) > 0:
        return False
    return True


def _fragment_score(target_name: str, fragment: str) -> int:
    score = 0
    if target_name and target_name in fragment:
        score += 4
    if re.search(r"\d|[一二三四五六七八九十百千万亿]+[倍年月日]", fragment):
        score += 8
    keywords = [
        "目标市值",
        "空间",
        "订单",
        "客户",
        "供应链",
        "涨价",
        "提价",
        "份额",
        "产能",
        "毛利",
        "净利",
        "业绩",
        "交付",
        "突破",
        "绑定",
        "独家",
        "龙头",
        "卡位",
        "安全边际",
    ]
    score += sum(3 for keyword in keywords if keyword in fragment)
    if 18 <= len(fragment) <= 90:
        score += 2
    return score


def _contains_contact_noise(text: str) -> bool:
    return bool(re.search(r"1[3-9]\d{9}|\b\d{3,4}[- ]?\d{7,8}\b", text))


def _other_target_count(
    target_name: str,
    text: str,
    target_names: set[str],
) -> int:
    return sum(
        1
        for name in target_names
        if name and name != target_name and len(name) >= 2 and name in text
    )


def _clip_text(text: str, max_len: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip(" ，,；;")
    if len(compact) <= max_len:
        return compact
    clipped = compact[:max_len].rstrip(" ，,；;")
    if "，" in clipped:
        clipped = clipped.rsplit("，", 1)[0]
    return clipped.rstrip(" ，,；;") or compact[:max_len].rstrip(" ，,；;")


def _clean_boss_line(text: str, max_len: int) -> str:
    line = _clean_fragment(text)
    line = line.replace("...", "，").replace("…", "，")
    line = re.sub(r"\s+", " ", line).strip(" ，,；;")
    return _clip_text(line, max_len=max_len)


def _is_valid_boss_line(
    target_name: str,
    line: str,
    target_names: set[str],
) -> bool:
    if len(line) < 18 or len(line) > 150:
        return False
    if "..." in line or "…" in line:
        return False
    if _contains_contact_noise(line):
        return False
    if _other_target_count(target_name, line, target_names) > 0:
        return False
    return True


def _display_dt(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def _parse_clock(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"非法时间格式，期望 HH:MM: {value}") from exc


def _run_publish_cmd(args: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode == 0:
        return
    stderr = result.stderr.strip() or result.stdout.strip()
    raise RuntimeError(stderr or f"命令失败: {args[0]}")
