"""每日晚报功能分层实现."""

from stock_news.signals.nightly_report.builder import generate_nightly_report
from stock_news.signals.nightly_report.models import NightlyOutput, PublishOutput
from stock_news.signals.nightly_report.paths import nightly_paths
from stock_news.signals.nightly_report.publish import publish_nightly_html
from stock_news.signals.nightly_report.render import render_nightly_html
from stock_news.signals.nightly_report.time import parse_datetime_expr

__all__ = [
    "NightlyOutput",
    "PublishOutput",
    "generate_nightly_report",
    "nightly_paths",
    "parse_datetime_expr",
    "publish_nightly_html",
    "render_nightly_html",
]
