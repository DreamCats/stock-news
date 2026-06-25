"""催化词库合并逻辑。

内置词库提供保守默认值，用户配置只表达禁用、追加和自定义分类。
"""

from __future__ import annotations

from stock_news.core.source_messages.builtin_terms import builtin_catalyst_library
from stock_news.core.source_messages.models import CatalystCategory, CatalystTermLibrary
from stock_news.models import CatalystConfig


def build_catalyst_library(config: CatalystConfig | None = None) -> CatalystTermLibrary:
    """按内置词库和用户配置生成最终可匹配词库。"""

    config = config or CatalystConfig()
    categories: dict[str, CatalystCategory] = {}

    if config.builtin_enabled:
        for category in builtin_catalyst_library().categories:
            override = config.categories.get(category.id)
            if override is not None and not override.enabled:
                continue
            disabled_terms = set(override.disabled_terms if override else [])
            terms = [term for term in category.terms if term not in disabled_terms]
            if override is not None:
                terms.extend(override.extra_terms)
            categories[category.id] = CatalystCategory(
                id=category.id,
                name=category.name,
                color=category.color,
                terms=tuple(_normalize_terms(terms)),
            )

    for custom in config.custom_categories:
        if not custom.enabled:
            continue
        existing = categories.get(custom.id)
        if existing is None:
            categories[custom.id] = CatalystCategory(
                id=custom.id,
                name=custom.name,
                color=custom.color,
                terms=tuple(_normalize_terms(custom.terms)),
            )
            continue
        categories[custom.id] = CatalystCategory(
            id=custom.id,
            name=custom.name or existing.name,
            color=custom.color or existing.color,
            terms=tuple(_normalize_terms([*existing.terms, *custom.terms])),
        )

    return CatalystTermLibrary(
        version=config.version,
        categories=tuple(categories.values()),
    )


def _normalize_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return terms
