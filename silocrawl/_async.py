"""Async-first SiloCrawl client."""
from __future__ import annotations

import os
from typing import Any

from app.core.config import get_settings
from app.models.schemas import (
    CrawlRequest,
    ExtractRequest,
    MapRequest,
    OutputFormat,
    ScrapeRequest,
    ScrapeResult,
)
from app.services import crawler, extractor, mapper, scraper


class AsyncSiloCrawl:
    """Async SiloCrawl client — use with ``await``.

    Parameters
    ----------
    hf_api_key:
        HuggingFace API key for LLM-powered extraction.
        Falls back to the ``HF_API_KEY`` environment variable.
    hf_endpoint_url:
        HuggingFace Inference Endpoint URL.
        Falls back to ``HF_ENDPOINT_URL``.
    extract_model:
        Model ID to use for extraction. Defaults to ``openai/gpt-oss-120b``.
    request_timeout:
        HTTP request timeout in seconds. Defaults to 30.

    Examples
    --------
    >>> import asyncio
    >>> from silocrawl import AsyncSiloCrawl
    >>> sc = AsyncSiloCrawl(hf_api_key="hf_...")
    >>> result = asyncio.run(sc.scrape("https://example.com"))
    >>> print(result.markdown)
    """

    def __init__(
        self,
        hf_api_key: str | None = None,
        hf_endpoint_url: str | None = None,
        extract_model: str | None = None,
        request_timeout: float | None = None,
    ) -> None:
        if hf_api_key:
            os.environ["HF_API_KEY"] = hf_api_key
        if hf_endpoint_url:
            os.environ["HF_ENDPOINT_URL"] = hf_endpoint_url
        if extract_model:
            os.environ["EXTRACT_MODEL"] = extract_model
        if request_timeout is not None:
            os.environ["REQUEST_TIMEOUT"] = str(request_timeout)
        get_settings.cache_clear()

    async def scrape(
        self,
        url: str,
        *,
        formats: list[str] | None = None,
        render_js: bool = False,
        only_main_content: bool = True,
    ) -> ScrapeResult:
        """Fetch a URL and return clean content.

        Parameters
        ----------
        url:
            The URL to scrape.
        formats:
            List of output formats. Any of ``"markdown"``, ``"html"``,
            ``"text"``, ``"links"``. Defaults to ``["markdown"]``.
        render_js:
            Use Playwright to render JavaScript before extracting.
        only_main_content:
            Strip navigation/ads and return only the main body content.

        Returns
        -------
        ScrapeResult
            Object with ``.markdown``, ``.html``, ``.text``, ``.links``,
            and ``.metadata`` fields.
        """
        fmts = [OutputFormat(f) for f in (formats or ["markdown"])]
        return await scraper.scrape(
            ScrapeRequest(
                url=url,
                formats=fmts,
                render_js=render_js,
                only_main_content=only_main_content,
            )
        )

    async def map(self, url: str, *, limit: int = 500) -> list[str]:
        """Discover all URLs on a domain.

        Combines sitemap.xml parsing and homepage link extraction.

        Parameters
        ----------
        url:
            Root URL of the domain to map.
        limit:
            Maximum number of URLs to return.

        Returns
        -------
        list[str]
            Sorted list of discovered URLs.
        """
        result = await mapper.map_site(MapRequest(url=url, limit=limit))
        return result.links

    async def extract(
        self,
        url: str | None = None,
        *,
        content: str | None = None,
        schema: dict[str, Any],
        prompt: str | None = None,
        render_js: bool = False,
    ) -> dict[str, Any]:
        """Extract structured data from a URL or raw content using an LLM.

        Parameters
        ----------
        url:
            URL to scrape and extract from.
            Either ``url`` or ``content`` must be provided.
        content:
            Raw markdown/text to extract from directly (skips scraping).
        schema:
            JSON Schema describing the structure to extract.
        prompt:
            Optional natural-language instruction for the LLM.
        render_js:
            Render JavaScript before scraping.

        Returns
        -------
        dict
            Extracted data conforming to the provided schema.

        Examples
        --------
        >>> data = await sc.extract(
        ...     "https://example.com",
        ...     schema={
        ...         "type": "object",
        ...         "properties": {
        ...             "title": {"type": "string"},
        ...             "summary": {"type": "string"},
        ...         },
        ...     },
        ... )
        >>> print(data["title"])
        """
        result = await extractor.extract(
            ExtractRequest(
                url=url,
                content=content,
                json_schema=schema,
                prompt=prompt,
                render_js=render_js,
            )
        )
        return result.data

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int = 10,
        max_depth: int = 3,
        formats: list[str] | None = None,
        render_js: bool = False,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        allow_external: bool = False,
    ) -> list[ScrapeResult]:
        """Recursively crawl a site and return all scraped pages.

        Parameters
        ----------
        url:
            Starting URL for the crawl.
        max_pages:
            Maximum number of pages to crawl.
        max_depth:
            Maximum link-follow depth from the starting URL.
        formats:
            Output formats for each page. Defaults to ``["markdown"]``.
        render_js:
            Use Playwright to render JavaScript on every page.
        include_paths:
            Regex patterns — only URLs matching at least one are followed.
            Example: ``["/blog", "/articles"]``
        exclude_paths:
            Regex patterns — URLs matching any are skipped.
            Example: ``["/live", "/scores"]``
        allow_external:
            Follow links to external domains. Defaults to ``False``.

        Returns
        -------
        list[ScrapeResult]
            One ``ScrapeResult`` per successfully crawled page.
        """
        fmts = [OutputFormat(f) for f in (formats or ["markdown"])]
        req = CrawlRequest(
            url=url,
            max_pages=max_pages,
            max_depth=max_depth,
            formats=fmts,
            render_js=render_js,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            allow_external=allow_external,
        )
        results, _ = await crawler.crawl(req)
        return results
