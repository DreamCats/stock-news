"""消息分析子命令：classify / extract / opinion / pipeline / show."""

from stock_news.commands.analyze.classify import classify
from stock_news.commands.analyze.extract import extract
from stock_news.commands.analyze.opinion import opinion
from stock_news.commands.analyze.pipeline import pipeline
from stock_news.commands.analyze.show import show_analysis

__all__ = ["classify", "extract", "opinion", "pipeline", "show_analysis"]
