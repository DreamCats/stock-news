"""Prompt 模板加载与渲染."""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path.home() / ".config" / "stock-news" / "prompts"

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
    "report_summary": """\
你是一个投研助理。根据以下今日推荐数据和观点变化，写一段 3-5 句话的今日摘要，面向投资决策者。

要求：
- 先说今天最值得关注的方向/板块
- 点出共识最强的标的（多人推荐）
- 提到关键的观点变化（反转、修正）
- 语言简洁专业，不要废话
- 用 **双星号** 包裹关键词（标的名称、板块名称、核心动作如"反转""卖出"），方便高亮展示
- 返回纯文本（可用 **标记**），不要 JSON

今日推荐数据：
{recommendations}

今日观点变化：
{opinions}""",
    "report_logic": """\
你是一个投研助理。将以下多位分析师对同一标的的推荐理由归纳为一段完整的投资逻辑。

要求：
- 去重合并相似观点
- 按重要性排序，先说核心逻辑，再说辅助论据
- 如果有分歧（比如有人看多有人看空），要体现出来
- 2-4 句话，简洁专业
- 返回纯文本，不要 JSON

标的：{ticker}
推荐详情：
{details}""",
}


def ensure_prompts_dir() -> None:
    """确保 prompts 目录存在，写入内置模板（不覆盖已有）."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in BUILTIN_PROMPTS.items():
        path = PROMPTS_DIR / f"{name}.txt"
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def load_prompt(name: str) -> str:
    """加载 prompt 模板，优先用户自定义，回退内置."""
    user_path = PROMPTS_DIR / f"{name}.txt"
    if user_path.exists():
        return user_path.read_text(encoding="utf-8")
    if name in BUILTIN_PROMPTS:
        return BUILTIN_PROMPTS[name]
    raise FileNotFoundError(f"Prompt 模板 '{name}' 不存在")


def render_prompt(name: str, **kwargs: str) -> str:
    """加载并渲染 prompt 模板."""
    template = load_prompt(name)
    return template.format(**kwargs)
