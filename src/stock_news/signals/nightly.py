"""每日晚报兼容入口."""

from stock_news.signals.nightly_report import (
    NightlyOutput,
    PublishOutput,
    generate_nightly_report,
    nightly_paths,
    parse_datetime_expr,
    publish_nightly_html,
    render_nightly_html,
)

__all__ = [
    "NightlyOutput",
    "PublishOutput",
    "generate_nightly_report",
    "nightly_paths",
    "parse_datetime_expr",
    "publish_nightly_html",
    "render_nightly_html",
]
