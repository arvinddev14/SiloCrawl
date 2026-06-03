"""Turn raw HTML into clean markdown / text / links plus page metadata."""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import trafilatura
from markdownify import markdownify as md
from selectolax.parser import HTMLParser

from app.models.schemas import OutputFormat, PageMetadata, ScrapeResult


def _extract_metadata(tree: HTMLParser, url: str, status_code: int) -> PageMetadata:
    def meta(name: str, attr: str = "name") -> str | None:
        node = tree.css_first(f'meta[{attr}="{name}"]')
        return node.attributes.get("content") if node else None

    title_node = tree.css_first("title")
    html_node = tree.css_first("html")
    return PageMetadata(
        title=(title_node.text() if title_node else None) or meta("og:title", "property"),
        description=meta("description") or meta("og:description", "property"),
        language=(html_node.attributes.get("lang") if html_node else None),
        status_code=status_code,
        source_url=url,
    )


def _extract_links(tree: HTMLParser, base_url: str) -> list[str]:
    out: set[str] = set()
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme in ("http", "https"):
            out.add(absolute.split("#")[0])
    return sorted(out)


def _prune(tree: HTMLParser, include: list[str] | None, exclude: list[str] | None) -> None:
    if exclude:
        for sel in exclude:
            for node in tree.css(sel):
                node.decompose()
    # strip noise by default
    for sel in ("script", "style", "noscript", "iframe", "svg"):
        for node in tree.css(sel):
            node.decompose()


def clean(
    html: str,
    url: str,
    status_code: int,
    formats: list[OutputFormat],
    only_main_content: bool = True,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
) -> ScrapeResult:
    tree = HTMLParser(html)
    metadata = _extract_metadata(tree, url, status_code)
    _prune(tree, include_tags, exclude_tags)

    result = ScrapeResult(metadata=metadata)

    if OutputFormat.links in formats:
        result.links = _extract_links(tree, url)

    if OutputFormat.html in formats:
        result.html = tree.html

    # Main-content extraction for markdown/text
    body_html = html
    if only_main_content:
        extracted = trafilatura.extract(
            html, output_format="html", include_links=True, include_tables=True
        )
        if extracted:
            body_html = extracted

    if OutputFormat.markdown in formats:
        result.markdown = md(body_html, heading_style="ATX").strip()

    if OutputFormat.text in formats:
        txt = trafilatura.extract(html) if only_main_content else HTMLParser(body_html).text()
        result.text = (txt or "").strip()

    return result
