"""盘中策略快报生成."""

from __future__ import annotations

from stock_news.common.config import load

from . import entrypoint as _entrypoint
from . import llm as _llm_module
from .llm import _generate_llm_logic


def generate(
    date_str: str,
    window_minutes: int,
    top: int,
    json_output: bool,
    use_llm: bool = False,
    provider_name: str | None = None,
) -> None:
    """生成盘中策略快报 JSON 和 Markdown."""
    setattr(_entrypoint, "load", globals()["load"])
    setattr(_llm_module, "_generate_llm_logic", globals()["_generate_llm_logic"])
    _entrypoint.generate(
        date_str,
        window_minutes,
        top,
        json_output,
        use_llm,
        provider_name,
    )


__all__ = [
    "generate",
    "load",
    "_generate_llm_logic",
]
