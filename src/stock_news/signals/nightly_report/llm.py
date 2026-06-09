"""每日晚报 LLM 改写与裁判."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stock_news.common.config import load
from stock_news.common.llm.task_pool import (
    chunked,
    resolve_provider_pool,
    run_provider_batches,
    select_provider,
)
from stock_news.signals.nightly_report.material import (
    clean_boss_line,
    is_valid_boss_line,
)

NIGHTLY_BATCH_SIZE = 16
NIGHTLY_BATCH_WORKERS = 2


def attach_boss_lines(
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
            if boss_line and is_valid_boss_line(target_name, boss_line, target_names):
                item["brief"] = clean_boss_line(boss_line, max_len=135)
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
        "batch_size": NIGHTLY_BATCH_SIZE,
        "batch_workers": NIGHTLY_BATCH_WORKERS,
    }


def _generate_boss_lines_in_batches(
    items: list[dict[str, Any]],
    providers: tuple[str | None, ...],
    batch_dir: Path,
) -> dict[str, str]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    batches = chunked(items, NIGHTLY_BATCH_SIZE)
    results = run_provider_batches(
        batches,
        providers,
        NIGHTLY_BATCH_WORKERS,
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
        boss_line = clean_boss_line(
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
