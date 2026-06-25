"""公开研究源抓取器。

这里负责从官方 sitemap 发现 AI 相关公开研究内容，并把新增页面或 PDF 落盘。
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from stock_news.core.research_sources.models import (
    FetchedResearchDocument,
    ResearchCandidate,
    ResearchDocumentRecord,
    ResearchSyncError,
    ResearchSyncSummary,
)
from stock_news.core.research_sources.sqlite_store import ResearchSourceSQLiteStore
from stock_news.models import ResearchSourceProviderConfig, ResearchSourcesConfig

_TEXT_EXTENSIONS = (".html", ".htm", "")
_PDF_MIME = "application/pdf"
_DATE_RE = re.compile(
    r"\b("
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?"
    r")\s+\d{1,2},\s+\d{4}\b"
)
_VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_SKIP_HTML_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "form",
    "button",
    "select",
    "option",
}
_SKIP_ATTR_MARKERS = (
    "navigation",
    "primary-nav",
    "primary-navigation",
    "footer",
    "breadcrumb",
    "country-selector",
    "countries-container",
    "share",
    "social",
    "modal",
    "search",
    "cookie",
    "related",
    "previous-podcast",
    "next-podcast",
    "skip-link",
)
_BREAK_HTML_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "section"}


class ResearchSourceFetcher:
    """公开研究源同步器。"""

    def __init__(self, config: ResearchSourcesConfig) -> None:
        self.config = config
        self.store = ResearchSourceSQLiteStore(config.db_path)

    def sync(
        self,
        *,
        source_ids: list[str] | None = None,
        max_pages: int | None = None,
        refresh: bool = False,
        dry_run: bool = False,
        candidate_since: datetime | None = None,
        now: datetime | None = None,
    ) -> ResearchSyncSummary:
        """发现并抓取公开研究源新增内容。"""

        current = now or datetime.now().astimezone()
        sources = _selected_sources(self.config, source_ids)
        candidates, discovery_errors = self._discover_candidates_with_errors(
            source_ids=source_ids
        )
        if candidate_since is not None:
            candidates = [
                candidate
                for candidate in candidates
                if _candidate_after(candidate, candidate_since)
            ]
        if dry_run:
            return ResearchSyncSummary(
                sources=len(sources),
                candidates=len(candidates),
                fetched=0,
                inserted=0,
                updated=0,
                unchanged=0,
                skipped=0,
                failed=len(discovery_errors),
                dry_run=True,
                errors=discovery_errors,
            )

        page_budget = max_pages or self.config.max_pages_per_run
        fetched = inserted = updated = unchanged = skipped = 0
        failed = len(discovery_errors)
        errors = list(discovery_errors)

        for candidate in candidates:
            if fetched >= page_budget:
                skipped += 1
                continue
            if not refresh and self.store.has_current_candidate(candidate):
                skipped += 1
                continue
            try:
                doc = self.fetch_candidate(candidate, now=current)
                status = self.store.upsert_document(doc)
                fetched += 1
                if status == "inserted":
                    inserted += 1
                elif status == "updated":
                    updated += 1
                else:
                    unchanged += 1
            except Exception as exc:
                failed += 1
                error = ResearchSyncError(
                    source_id=candidate.source_id,
                    url=candidate.url,
                    error=str(exc),
                )
                errors.append(error)
                self.store.mark_failure(candidate, str(exc))

        return ResearchSyncSummary(
            sources=len(sources),
            candidates=len(candidates),
            fetched=fetched,
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            skipped=skipped,
            failed=failed,
            dry_run=False,
            errors=errors,
        )

    def discover_candidates(
        self,
        *,
        source_ids: list[str] | None = None,
    ) -> list[ResearchCandidate]:
        """从配置中的 sitemap 发现候选 URL。"""

        candidates, _ = self._discover_candidates_with_errors(source_ids=source_ids)
        return candidates

    def _discover_candidates_with_errors(
        self,
        *,
        source_ids: list[str] | None = None,
    ) -> tuple[list[ResearchCandidate], list[ResearchSyncError]]:
        """从 sitemap 发现候选 URL，并记录单个 sitemap 的失败。"""

        candidates: list[ResearchCandidate] = []
        errors: list[ResearchSyncError] = []
        seen: set[str] = set()
        for source_id, source in _selected_sources(self.config, source_ids).items():
            for sitemap_url in source.sitemap_urls:
                try:
                    sitemap_rows = self._walk_sitemap(sitemap_url)
                except Exception as exc:
                    errors.append(
                        ResearchSyncError(
                            source_id=source_id,
                            url=sitemap_url,
                            error=str(exc),
                        )
                    )
                    continue
                for url, lastmod in sitemap_rows:
                    if url in seen:
                        continue
                    if not _matches_source_url(source, url):
                        continue
                    seen.add(url)
                    candidates.append(
                        ResearchCandidate(
                            source_id=source_id,
                            source_name=source.name,
                            url=url,
                            sitemap_lastmod=lastmod,
                        )
                    )
        candidates.sort(key=_candidate_sort_key, reverse=True)
        return candidates, errors

    def fetch_candidate(
        self,
        candidate: ResearchCandidate,
        *,
        now: datetime | None = None,
    ) -> FetchedResearchDocument:
        """抓取单条候选内容，并将正文或 PDF 保存到本地。"""

        current = now or datetime.now().astimezone()
        body, content_type = self._read_url(candidate.url)
        sha = hashlib.sha256(body).hexdigest()
        date_dir = Path(self.config.data_dir).expanduser() / current.strftime(
            "%Y-%m-%d"
        )
        date_dir.mkdir(parents=True, exist_ok=True)

        if _is_pdf(candidate.url, content_type):
            binary_path_obj = date_dir / f"{sha[:16]}.pdf"
            binary_path_obj.write_bytes(body)
            title = _title_from_url(candidate.url)
            text_path = ""
            binary_path = str(binary_path_obj)
            published_at = candidate.sitemap_lastmod
        else:
            html = body.decode("utf-8", errors="replace")
            extracted = extract_html_text(html)
            title = extracted.title or _title_from_url(candidate.url)
            text = extracted.text
            if not _matches_content_keywords(
                title=title,
                text=text,
                keywords=_source_for_candidate(self.config, candidate).content_keywords,
            ):
                raise ValueError("正文未命中 AI 关键词")
            text_path_obj = date_dir / f"{sha[:16]}.txt"
            text_path_obj.write_text(text, encoding="utf-8")
            text_path = str(text_path_obj)
            binary_path = ""
            published_at = (
                extracted.published_at
                or candidate.sitemap_lastmod
                or _extract_date_from_text(text)
            )

        return FetchedResearchDocument(
            source_id=candidate.source_id,
            source_name=candidate.source_name,
            url=candidate.url,
            title=title,
            published_at=published_at,
            sitemap_lastmod=candidate.sitemap_lastmod,
            content_type=content_type,
            content_sha256=sha,
            text_path=text_path,
            binary_path=binary_path,
            fetched_at=current,
        )

    def list_documents(
        self,
        *,
        source_id: str | None = None,
        fetched_start: datetime | None = None,
        fetched_end: datetime | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[ResearchDocumentRecord]:
        """读取本地已抓取研究内容。"""

        return self.store.list_documents(
            source_id=source_id,
            fetched_start=fetched_start,
            fetched_end=fetched_end,
            status=status,
            limit=limit,
        )

    def _walk_sitemap(self, url: str, *, depth: int = 0) -> list[tuple[str, str]]:
        if depth > 3:
            return []
        body, _ = self._read_url(url)
        root = ET.fromstring(body)
        if _local_name(root.tag) == "sitemapindex":
            urls: list[tuple[str, str]] = []
            for item in root:
                if _local_name(item.tag) != "sitemap":
                    continue
                loc = _child_text(item, "loc")
                if loc:
                    urls.extend(self._walk_sitemap(loc, depth=depth + 1))
            return urls

        rows: list[tuple[str, str]] = []
        for item in root:
            if _local_name(item.tag) != "url":
                continue
            loc = _child_text(item, "loc")
            if not loc:
                continue
            rows.append((loc, _child_text(item, "lastmod")))
        return rows

    def _read_url(self, url: str) -> tuple[bytes, str]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as resp:
                content_type = resp.headers.get("content-type", "").split(";")[0]
                return resp.read(), content_type.lower()
        except urllib.error.HTTPError as exc:
            raise ValueError(f"HTTP {exc.code}: {url}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"请求失败: {url}: {exc.reason}") from exc


class ExtractedHTML:
    """HTML 正文抽取结果。"""

    def __init__(self, *, title: str, text: str, published_at: str) -> None:
        self.title = title
        self.text = text
        self.published_at = published_at


class _ReadableHTMLParser(HTMLParser):
    """轻量 HTML 正文抽取器。"""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.published_at = ""
        self._in_title = False
        self._skip_depth = 0
        self._tag_stack: list[tuple[str, bool]] = []
        self._chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = True
        if lowered == "meta":
            attrs_map = {key.lower(): value or "" for key, value in attrs}
            name = attrs_map.get("name") or attrs_map.get("property")
            content = attrs_map.get("content", "")
            if name and name.lower() in {
                "article:published_time",
                "date",
                "datepublished",
                "dcterms.date",
                "og:updated_time",
            }:
                self.published_at = content.strip()
            if name and name.lower() in {"description", "og:description"}:
                self.meta_description = content.strip()
            return
        skip_current = (
            self._skip_depth > 0
            or lowered in _SKIP_HTML_TAGS
            or _is_skip_element(attrs)
        )
        if lowered in _BREAK_HTML_TAGS and not skip_current:
            self._chunks.append("\n")
        if lowered not in _VOID_HTML_TAGS:
            self._tag_stack.append((lowered, skip_current))
            if skip_current:
                self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False
        self._pop_tag(lowered)

    def _pop_tag(self, tag: str) -> None:
        for index in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[index][0] != tag:
                continue
            popped = self._tag_stack[index:]
            del self._tag_stack[index:]
            self._skip_depth -= sum(1 for _, skipped in popped if skipped)
            self._skip_depth = max(self._skip_depth, 0)
            return

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self._chunks))

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
        self._chunks.append(cleaned)


def extract_html_text(html: str) -> ExtractedHTML:
    """抽取 HTML 标题、发布时间和正文文本。"""

    parser = _ReadableHTMLParser()
    parser.feed(html)
    text = _merge_description_and_text(parser.meta_description, parser.text)
    return ExtractedHTML(
        title=parser.title,
        text=text,
        published_at=parser.published_at or _extract_date_from_text(text),
    )


def _is_skip_element(attrs: list[tuple[str, str | None]]) -> bool:
    attrs_map = {key.lower(): value or "" for key, value in attrs}
    marker_text = " ".join(
        attrs_map.get(key, "") for key in ("id", "class", "role", "aria-label")
    ).lower()
    return any(marker in marker_text for marker in _SKIP_ATTR_MARKERS)


def _merge_description_and_text(description: str, text: str) -> str:
    cleaned_description = _normalize_text(description)
    if not cleaned_description:
        return text
    if cleaned_description.lower() in text.lower():
        return text
    if not text:
        return cleaned_description
    return _normalize_text(f"{cleaned_description}\n{text}")


def _selected_sources(
    config: ResearchSourcesConfig,
    source_ids: list[str] | None,
) -> dict[str, ResearchSourceProviderConfig]:
    if not config.enabled:
        return {}
    selected: dict[str, ResearchSourceProviderConfig] = {}
    requested = set(source_ids or [])
    for source_id, source in config.sources.items():
        if requested and source_id not in requested:
            continue
        if not source.enabled:
            continue
        selected[source_id] = source
    return selected


def _source_for_candidate(
    config: ResearchSourcesConfig,
    candidate: ResearchCandidate,
) -> ResearchSourceProviderConfig:
    source = config.sources.get(candidate.source_id)
    if source is None:
        raise ValueError(f"未知研究源: {candidate.source_id}")
    return source


def _candidate_sort_key(candidate: ResearchCandidate) -> tuple[str, str, str]:
    return (candidate.sitemap_lastmod, candidate.source_id, candidate.url)


def _candidate_after(candidate: ResearchCandidate, since: datetime) -> bool:
    parsed = _parse_sitemap_datetime(candidate.sitemap_lastmod)
    return parsed is not None and parsed >= since


def _parse_sitemap_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _matches_source_url(source: ResearchSourceProviderConfig, url: str) -> bool:
    lowered = url.lower()
    if any(item.lower() in lowered for item in source.exclude_url_keywords):
        return False
    if source.url_prefixes and not any(
        lowered.startswith(prefix.lower()) for prefix in source.url_prefixes
    ):
        return False
    if source.url_keywords and not any(
        keyword.lower() in lowered for keyword in source.url_keywords
    ):
        return False
    return True


def _matches_content_keywords(*, title: str, text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    blob = f"{title}\n{text}".lower()
    return any(keyword.lower() in blob for keyword in keywords)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _is_pdf(url: str, content_type: str) -> bool:
    return content_type == _PDF_MIME or url.lower().endswith(".pdf")


def _title_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(part for part in tail.replace("-", " ").split() if part)


def _normalize_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _extract_date_from_text(text: str) -> str:
    match = _DATE_RE.search(text)
    return match.group(0) if match else ""


def serialize_sync_summary(summary: ResearchSyncSummary) -> dict[str, object]:
    """把同步摘要转成 JSON 友好的 dict。"""

    data = asdict(summary)
    data["errors"] = [asdict(error) for error in summary.errors]
    return data


def absolute_url(base_url: str, value: str) -> str:
    """将页面内链接转成绝对 URL，供后续扩展附件提取复用。"""

    return urljoin(base_url, value)
