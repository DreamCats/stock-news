"""源头消息 core 能力测试。"""

from __future__ import annotations

from stock_news.core.source_messages import (
    SourceMessage,
    build_catalyst_library,
    cluster_dedupe_hash,
    contains_term,
    filter_catalyst_messages,
    match_catalysts,
    normalize_content,
)
from stock_news.models import (
    CatalystCategoryOverrideConfig,
    CatalystConfig,
    CatalystCustomCategoryConfig,
)


def test_builtin_catalyst_terms_match_message() -> None:
    library = build_catalyst_library()
    message = SourceMessage(
        message_id="m1",
        content="液冷材料出现涨价，排产已经满产。",
    )

    result = match_catalysts(message, library)

    assert result.has_hit is True
    assert {hit.term for hit in result.hits} >= {"涨价", "排产", "满产"}
    assert "price_supply" in {hit.category_id for hit in result.hits}


def test_ascii_term_uses_word_boundary() -> None:
    assert contains_term("机构 IR 交流纪要", "IR") is True
    assert contains_term("公司 FIR 滤波器交流", "IR") is False


def test_catalyst_config_merges_builtin_overrides_and_custom_terms() -> None:
    config = CatalystConfig(
        categories={
            "price_supply": CatalystCategoryOverrideConfig(
                extra_terms=["抢单"],
                disabled_terms=["涨价"],
            ),
            "market_confirmation": CatalystCategoryOverrideConfig(enabled=False),
        },
        custom_categories=[
            CatalystCustomCategoryConfig(
                id="ai_application",
                name="AI 应用",
                color="#38bdf8",
                terms=["商业化落地", "付费率提升"],
            )
        ],
    )
    library = build_catalyst_library(config)
    messages = [
        SourceMessage(message_id="m1", content="这次涨价先不算"),
        SourceMessage(message_id="m2", content="客户开始抢单，付费率提升"),
        SourceMessage(message_id="m3", content="涨停了"),
    ]

    results = filter_catalyst_messages(messages, library)

    assert [result.message.message_id for result in results] == ["m2"]
    assert {hit.term for hit in results[0].hits} == {"抢单", "付费率提升"}
    assert {hit.category_id for hit in results[0].hits} == {
        "price_supply",
        "ai_application",
    }


def test_normalize_content_strips_decorative_tokens_for_dedupe() -> None:
    first = "液冷涨价[玫瑰] https://example.com/a"
    second = "液冷 涨价！！！"

    assert normalize_content(first) == normalize_content(second)
    assert cluster_dedupe_hash([first]) == cluster_dedupe_hash([second])


def test_cluster_dedupe_prefers_long_substantive_message() -> None:
    long_text = (
        "液冷材料价格拐点出现，核心厂商排产满产，客户验证通过，"
        "后续可能批量交付，同时海外订单开始放量，行业库存低位。"
    )
    with_comment = [long_text, "转发一下[强]"]

    assert cluster_dedupe_hash(with_comment) == cluster_dedupe_hash([long_text])
