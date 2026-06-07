"""Prompt 模板加载与渲染."""
# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path.home() / ".config" / "stock-news" / "prompts"

_DYNAMIC_MARKERS: dict[str, tuple[str, ...]] = {
    "classify": ("消息来源：{source}",),
    "classify_batch": ("以下是待分类的消息：",),
    "extract": ("发送人：{sender}",),
    "extract_batch": ("以下是待抽取的消息：",),
    "source_extract": ("发送人：{sender}",),
    "source_extract_batch": ("以下是待抽取的消息：",),
    "source_brief": ("候选明细：",),
    "opinion": ("发送人：{sender}",),
    "opinion_batch": ("发送人：{sender}",),
}

_LEGACY_SOURCE_EXTRACT_MARKERS: dict[str, tuple[str, ...]] = {
    "source_extract": ("is_source_candidate", "source_type", "terms"),
    "source_extract_batch": ("is_source_candidate", "source_type", "terms"),
}

BUILTIN_PROMPTS: dict[str, str] = {
    "classify": """\
你是一个投研消息分类器。请判断以下消息属于哪种类型，返回纯 JSON（不要 markdown 代码块）。

类型定义：
- recommendation: 包含明确的个股/板块推荐、买入/关注/加仓/减仓建议
- research: 研究观点、行业分析、研报摘要，但没有明确交易建议
- event: 会议、调研、策略会、活动通知
- tool: 工具服务介绍、软件推荐、广告
- noise: 私人消息、闲聊、无关内容

返回格式：
{{"category": "recommendation|research|event|tool|noise", "confidence": 0.0到1.0, "reason": "一句话分类理由"}}

消息来源：{source}
发送人：{sender}
消息内容：
{raw_content}""",
    "extract": """\
你是一个投研推荐抽取器。从以下消息中抽取结构化推荐信息，返回纯 JSON（不要 markdown 代码块）。

如果消息包含多个标的推荐，返回 JSON 数组；如果只有一个，也返回数组（只有一个元素）。

每个推荐的字段：
- target_type: stock/sector/theme/index/macro/unknown
- target_name: 标的、板块、主题或宏观变量名称
- ticker: 股票名称或代码；如果不是个股，填 null
- market: A股/港股/美股，不确定或跨市场填 null
- action: 只能填 关注/买入/加仓/减仓/卖出
- strength: 高/中/低（根据措辞判断推荐强度）
- horizon: 日内/短线/波段/中线，不确定填 null
- reasoning: 一句话推荐理由
- risk_note: 风险提示，没有填 null
- confidence: 0.0到1.0，表示抽取置信度
- evidence: 支持该推荐的关键短句

返回格式：
[{{"target_type": "stock|sector|theme|index|macro|unknown", "target_name": "...", "ticker": "...", "market": "...", "action": "关注|买入|加仓|减仓|卖出", "strength": "高|中|低", "horizon": "...", "reasoning": "...", "risk_note": "...", "confidence": 0.0, "evidence": "..."}}]

注意：
- 板块/主题推荐也要抽取，不要因为没有具体个股而返回空数组
- action 必须归一到允许枚举，不要输出"看好/推荐/强推/首推/加推"

发送人：{sender}
消息内容：
{raw_content}""",
    "source_extract": """\
你是源头雷达的结构抽取器。你只负责从消息原文中切出“成熟锚点 + 陌生修饰/新表达”的组合结构，返回纯 JSON（不要 markdown 代码块）。

不要判断这个概念新不新、早不早、会不会涨；这些由本地历史证据计算。你只做可回指原文的 span 抽取。

必须满足：
- anchor_span、modifier_span、novel_span 都必须是原文中能定位到的短语或连续子串。
- novel_span 是完整组合，例如“半导体化的PCB”“CIPB-PCB”“AI电源”。
- anchor_span 是成熟产业链、技术、产品、客户、工艺、指标或场景锚点。
- modifier_span 是让这个锚点出现新意的修饰、路径、解法、前缀、应用或机制。
- 单纯个股推荐、带股票清单、上市/第一股、估值弹性、财报/业绩、买入逻辑不是源头候选。
- 没有明确组合结构时，is_candidate=false。

字段：
- is_candidate: true/false
- anchor_span: 原文中的成熟锚点 span
- modifier_span: 原文中的陌生修饰 span
- novel_span: 原文中的完整组合 span
- relation_type: A化B/prefix-anchor/modifier-anchor/anchor-extension/other
- relation_evidence: 支撑这个结构关系的原文短句
- ask_question: 拿去问产业大佬的一句话问题
- confidence: 0.0 到 1.0
- reject_reason: 不是候选时填写原因，否则 null

返回格式：
{{"is_candidate": true, "anchor_span": "...", "modifier_span": "...", "novel_span": "...", "relation_type": "A化B|prefix-anchor|modifier-anchor|anchor-extension|other", "relation_evidence": "...", "ask_question": "...", "confidence": 0.0, "reject_reason": null}}

发送人：{sender}
消息内容：
{raw_content}""",
    "opinion": """\
你是一个投研观点链分析器。判断当前消息相对于同一发送人的历史观点，属于什么类型的观点更新。

观点更新类型：
- new: 首次提出此标的/主题
- reinforce: 持续强化已有观点
- supplement: 补充新证据或论据
- revise: 修正之前的观点
- reverse: 观点完全反转
- withdraw: 撤回或否定之前的判断

返回纯 JSON（不要 markdown 代码块）：
{{"topic_key": "标的或主题关键词", "stance": "bullish|bearish|neutral|mixed", "update_type": "new|reinforce|supplement|revise|reverse|withdraw", "summary": "一句话观点摘要", "confidence": 0.0到1.0, "candidate_existing_topic": "最可能承接的历史 topic_key；没有则填 null"}}

注意：
- 如果当前消息是在延续历史主题，candidate_existing_topic 必须填历史里的原 topic_key
- 如果不确定是新主题还是历史主题，降低 confidence

发送人：{sender}
当前消息：
{raw_content}

该发送人近期相关历史观点：
{history}""",
    "opinion_batch": """\
你是一个投研观点链分析器。请对以下同一发送人的多条消息逐一判断观点更新类型，返回纯 JSON 数组（不要 markdown 代码块）。

观点更新类型：
- new: 首次提出此标的/主题
- reinforce: 持续强化已有观点
- supplement: 补充新证据或论据
- revise: 修正之前的观点
- reverse: 观点完全反转
- withdraw: 撤回或否定之前的判断

每个结果必须包含 index 字段（对应输入编号）。
返回格式：
[{{"index": 1, "topic_key": "标的或主题关键词", "stance": "bullish|bearish|neutral|mixed", "update_type": "new|reinforce|supplement|revise|reverse|withdraw", "summary": "一句话观点摘要", "confidence": 0.0到1.0, "candidate_existing_topic": "最可能承接的历史 topic_key；没有则填 null"}}, ...]

注意：
- 必须为每条消息都返回结果，不要遗漏
- index 必须与输入编号严格对应
- 请按输入编号顺序分析，前序消息视为后续消息的新增历史观点
- 如果某条消息无法判断观点，topic_key 填空字符串
- 如果当前消息是在延续历史主题，candidate_existing_topic 必须填历史里的原 topic_key
- 如果不确定是新主题还是历史主题，降低 confidence

发送人：{sender}

该发送人近期相关历史观点：
{history}

待分析消息：
{messages}""",
    "classify_batch": """\
你是一个投研消息分类器。请对以下多条消息逐一分类，返回纯 JSON 数组（不要 markdown 代码块）。

类型定义：
- recommendation: 包含明确的个股/板块推荐、买入/关注/加仓/减仓建议
- research: 研究观点、行业分析、研报摘要，但没有明确交易建议
- event: 会议、调研、策略会、活动通知
- tool: 工具服务介绍、软件推荐、广告
- noise: 私人消息、闲聊、无关内容

返回格式（必须包含 index 字段，与输入编号对应）：
[{{"index": 1, "category": "recommendation|research|event|tool|noise", "confidence": 0.0到1.0, "reason": "一句话分类理由"}}, ...]

注意：
- 必须为每条消息都返回结果，不要遗漏
- index 必须与输入编号严格对应

以下是待分类的消息：
{messages}""",
    "extract_batch": """\
你是一个投研推荐抽取器。从以下多条消息中分别抽取结构化推荐信息，返回纯 JSON 数组（不要 markdown 代码块）。

每个结果必须包含 index 字段（对应输入编号），以及 items 数组（该消息抽取出的推荐列表）。
如果某条消息无法抽取推荐，items 为空数组。

每个推荐的字段：
- target_type: stock/sector/theme/index/macro/unknown
- target_name: 标的、板块、主题或宏观变量名称
- ticker: 股票名称或代码；如果不是个股，填 null
- market: A股/港股/美股，不确定或跨市场填 null
- action: 只能填 关注/买入/加仓/减仓/卖出
- strength: 高/中/低（根据措辞判断推荐强度）
- horizon: 日内/短线/波段/中线，不确定填 null
- reasoning: 一句话推荐理由
- risk_note: 风险提示，没有填 null
- confidence: 0.0到1.0，表示抽取置信度
- evidence: 支持该推荐的关键短句

返回格式：
[{{"index": 1, "items": [{{"target_type": "stock|sector|theme|index|macro|unknown", "target_name": "...", "ticker": "...", "market": "...", "action": "关注|买入|加仓|减仓|卖出", "strength": "高|中|低", "horizon": "...", "reasoning": "...", "risk_note": "...", "confidence": 0.0, "evidence": "..."}}]}}, ...]

注意：
- 必须为每条消息都返回结果（即使 items 为空），不要遗漏
- index 必须与输入编号严格对应
- 板块/主题推荐也要抽取，不要因为没有具体个股而返回空数组
- action 必须归一到允许枚举，不要输出"看好/推荐/强推/首推/加推"

以下是待抽取的消息：
{messages}""",
    "source_extract_batch": """\
你是源头雷达的结构抽取器。请对以下多条投研消息逐一切出“成熟锚点 + 陌生修饰/新表达”的组合结构，返回纯 JSON 数组（不要 markdown 代码块）。

不要判断这个概念新不新、早不早、会不会涨；这些由本地历史证据计算。你只做可回指原文的 span 抽取。

每个结果必须包含 index 字段（对应输入编号）。
字段：
- is_candidate: true/false
- anchor_span: 原文中的成熟锚点 span
- modifier_span: 原文中的陌生修饰 span
- novel_span: 原文中的完整组合 span
- relation_type: A化B/prefix-anchor/modifier-anchor/anchor-extension/other
- relation_evidence: 支撑这个结构关系的原文短句
- ask_question: 拿去问产业大佬的一句话问题
- confidence: 0.0 到 1.0
- reject_reason: 不是候选时填写原因，否则 null

返回格式：
[{{"index": 1, "is_candidate": true, "anchor_span": "...", "modifier_span": "...", "novel_span": "...", "relation_type": "A化B|prefix-anchor|modifier-anchor|anchor-extension|other", "relation_evidence": "...", "ask_question": "...", "confidence": 0.0, "reject_reason": null}}]

注意：
- 必须为每条消息都返回结果，不要遗漏。
- index 必须与输入编号严格对应。
- anchor_span、modifier_span、novel_span 必须能在原文中定位；不能输出总结词、改写词或脑补词。
- 单纯个股推荐、带股票清单、上市/第一股、估值弹性、财报/业绩、买入逻辑不是源头候选。
- 没有明确组合结构时，is_candidate=false，并说明 reject_reason。

以下是待抽取的消息：
{messages}""",
    "source_brief": """\
你是给老板发投研源头提示的助理。请把源头候选压缩成自然、可扫读的老板版 Markdown。

要求：
- 只输出 Markdown 正文，不要解释你的任务。
- 标题写成一句吸引老板注意的中文提示，允许 1 个表情；不要出现 stock-news、源头提示、内部项目名。
- 只输出 2 到 3 条，每条 1 到 2 句话。
- 正文必须使用 `1. ...`、`2. ...`、`3. ...` 的编号列表，不要用无序列表或普通段落。
- 每条要有钩子：这是什么新东西、为什么现在值得看、有没有扩散或接力迹象；表达要像给老板发的提醒，不要像研报摘要。
- 可以把相关候选合并成一个更有冲击力的主题，但不要遗漏关键事实。
- 不要表格，不要算法指标名，不要原文长摘录，不要出现 anchor/modifier/exact/combo/status 等内部字段。
- 不要重新排序或脑补事实；只基于候选明细改写。
- 全文控制在 350 字以内。

候选明细：
{detail_markdown}""",
}


def ensure_prompts_dir() -> None:
    """确保 prompts 目录存在；内置 prompt 统一由主库管理.

    ~/.config/stock-news/prompts 只保留显式自定义覆盖，避免默认模板在配置目录
    生成副本后和主库版本漂移。
    """
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in _LEGACY_SOURCE_EXTRACT_MARKERS:
        path = PROMPTS_DIR / f"{name}.txt"
        if not path.exists():
            continue
        current = path.read_text(encoding="utf-8")
        suffix = "legacy" if _is_legacy_source_extract_copy(name, current) else "local"
        backup = PROMPTS_DIR / f"{name}.{suffix}.txt"
        if not backup.exists():
            backup.write_text(current, encoding="utf-8")
        path.unlink()


def load_prompt(name: str) -> str:
    """加载 prompt 模板，优先用户自定义，回退内置."""
    user_path = PROMPTS_DIR / f"{name}.txt"
    if user_path.exists() and name not in _LEGACY_SOURCE_EXTRACT_MARKERS:
        content = user_path.read_text(encoding="utf-8")
        if not _is_legacy_source_extract_copy(name, content):
            return content
    if name in BUILTIN_PROMPTS:
        return BUILTIN_PROMPTS[name]
    raise FileNotFoundError(f"Prompt 模板 '{name}' 不存在")


def _split_builtin_prompt(name: str) -> tuple[str, str] | None:
    """把内置 prompt 拆成稳定 system 指令和动态 user 输入."""
    template = BUILTIN_PROMPTS.get(name)
    if template is None:
        return None

    for marker in _DYNAMIC_MARKERS.get(name, ()):
        index = template.find(marker)
        if index == -1:
            continue
        system_prompt = template[:index].strip()
        user_prompt = template[index:].strip()
        return system_prompt, user_prompt
    return None


def _is_builtin_copy(name: str, content: str) -> bool:
    builtin = BUILTIN_PROMPTS.get(name)
    return builtin is not None and content.strip() == builtin.strip()


def _is_legacy_source_extract_copy(name: str, content: str) -> bool:
    markers = _LEGACY_SOURCE_EXTRACT_MARKERS.get(name)
    if markers is None:
        return False
    return all(marker in content for marker in markers)


def render_prompt(name: str, **kwargs: str) -> str:
    """加载并渲染 prompt 模板."""
    template = load_prompt(name)
    return template.format(**kwargs)


def render_prompt_messages(name: str, **kwargs: str) -> list[dict[str, str]]:
    """渲染为 chat messages，让稳定指令前缀更容易命中 prompt cache."""
    system_path = PROMPTS_DIR / f"{name}.system.txt"
    user_path = PROMPTS_DIR / f"{name}.user.txt"
    if system_path.exists() and user_path.exists():
        system_prompt = system_path.read_text(encoding="utf-8").format(**kwargs)
        user_prompt = user_path.read_text(encoding="utf-8").format(**kwargs)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    plain_path = PROMPTS_DIR / f"{name}.txt"
    if plain_path.exists() and name not in _LEGACY_SOURCE_EXTRACT_MARKERS:
        content = plain_path.read_text(encoding="utf-8")
        if not _is_builtin_copy(name, content) and not _is_legacy_source_extract_copy(
            name, content
        ):
            return [{"role": "user", "content": content.format(**kwargs)}]

    split_prompt = _split_builtin_prompt(name)
    if split_prompt is None:
        return [{"role": "user", "content": render_prompt(name, **kwargs)}]

    system_prompt, user_prompt = split_prompt
    return [
        {"role": "system", "content": system_prompt.format(**kwargs)},
        {"role": "user", "content": user_prompt.format(**kwargs)},
    ]
