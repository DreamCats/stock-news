"""公开研究源抓取测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_news.core.research_sources import ResearchSourceFetcher, extract_html_text
from stock_news.models import ResearchSourceProviderConfig, ResearchSourcesConfig


class FakeResearchSourceFetcher(ResearchSourceFetcher):
    """用内存响应替代真实网络的研究源抓取器。"""

    def __init__(
        self,
        config: ResearchSourcesConfig,
        responses: dict[str, tuple[bytes, str]],
    ) -> None:
        super().__init__(config)
        self.responses = responses

    def _read_url(self, url: str) -> tuple[bytes, str]:
        return self.responses[url]


def test_extract_html_text_reads_title_date_and_body() -> None:
    html = """
    <html>
      <head>
        <title>AI Infrastructure Report</title>
        <meta name="date" content="2026-06-25" />
        <script>ignore()</script>
      </head>
      <body><h1>AI capex</h1><p>Artificial intelligence data center buildout.</p></body>
    </html>
    """

    extracted = extract_html_text(html)

    assert extracted.title == "AI Infrastructure Report"
    assert extracted.published_at == "2026-06-25"
    assert "Artificial intelligence data center buildout." in extracted.text
    assert "ignore" not in extracted.text


def test_extract_html_text_skips_navigation_and_keeps_transcript() -> None:
    html = """
    <html>
      <head>
        <title>Powering the AI revolution</title>
        <meta
          property="og:description"
          content="AI is transforming global economies."
        />
      </head>
      <body>
        <div class="cmp-primary-navigation">
          <a>Solutions</a>
          <div class="description">Commercial Banking boilerplate.</div>
        </div>
        <div class="podcast-page-header">
          <div class="cmp-brightcove__transcript hide">
            <p><b>Speaker:</b> AI value chain includes data centers and chips.</p>
            <p>Power, turbines and grid connections are downstream constraints.</p>
          </div>
        </div>
        <footer>Privacy Terms of Use</footer>
      </body>
    </html>
    """

    extracted = extract_html_text(html)

    assert extracted.title == "Powering the AI revolution"
    assert "AI is transforming global economies." in extracted.text
    assert "AI value chain includes data centers and chips." in extracted.text
    assert "Power, turbines and grid connections" in extracted.text
    assert "Solutions" not in extracted.text
    assert "Commercial Banking boilerplate" not in extracted.text
    assert "Privacy Terms of Use" not in extracted.text


def test_sync_ai_research_sources_is_incremental(tmp_path: Path) -> None:
    cfg = ResearchSourcesConfig(
        db_path=str(tmp_path / "research.db"),
        data_dir=str(tmp_path / "data"),
        max_pages_per_run=5,
        sources={
            "test": ResearchSourceProviderConfig(
                name="测试投行",
                sitemap_urls=["https://example.com/sitemap.xml"],
                url_prefixes=["https://example.com/insights/"],
                url_keywords=["ai-"],
                content_keywords=["artificial intelligence"],
            )
        },
    )
    responses = {
        "https://example.com/sitemap.xml": (
            b"""
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://example.com/articles.xml</loc></sitemap>
            </sitemapindex>
            """,
            "application/xml",
        ),
        "https://example.com/articles.xml": (
            b"""
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url>
                <loc>https://example.com/insights/ai-report</loc>
                <lastmod>2026-06-25</lastmod>
              </url>
              <url>
                <loc>https://example.com/insights/rates-report</loc>
                <lastmod>2026-06-25</lastmod>
              </url>
            </urlset>
            """,
            "application/xml",
        ),
        "https://example.com/insights/ai-report": (
            b"""
            <html>
              <head><title>AI Report</title></head>
              <body>Artificial intelligence and data center investment.</body>
            </html>
            """,
            "text/html",
        ),
    }
    fetcher = FakeResearchSourceFetcher(cfg, responses)
    now = datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc)

    first = fetcher.sync(now=now)
    second = fetcher.sync(now=now)

    assert first.candidates == 1
    assert first.fetched == 1
    assert first.inserted == 1
    assert first.failed == 0
    assert second.fetched == 0
    assert second.skipped == 1
    rows = fetcher.list_documents()
    assert len(rows) == 1
    assert rows[0].source_name == "测试投行"
    assert rows[0].title == "AI Report"
    assert Path(rows[0].text_path).exists()

    today_rows = fetcher.list_documents(
        fetched_start=now - timedelta(seconds=1),
        fetched_end=now + timedelta(seconds=1),
        status="success",
        limit=10,
    )
    assert len(today_rows) == 1

    other_day_rows = fetcher.list_documents(
        fetched_start=now + timedelta(days=1),
        fetched_end=now + timedelta(days=2),
        status="success",
        limit=10,
    )
    assert other_day_rows == []
