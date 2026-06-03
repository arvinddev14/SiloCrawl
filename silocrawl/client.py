"""Synchronous SiloCrawl client."""
from __future__ import annotations

import asyncio
from typing import Any

from app.models.schemas import ScrapeResult
from silocrawl._async import AsyncSiloCrawl


class SiloCrawl:
    """Synchronous SiloCrawl client.

    All methods block until the operation completes. For use in async
    contexts (Jupyter, FastAPI, etc.) use :class:`AsyncSiloCrawl` instead.

    Parameters
    ----------
    hf_api_key:
        HuggingFace API key for LLM-powered extraction.
        Falls back to the ``HF_API_KEY`` environment variable.
    hf_endpoint_url:
        HuggingFace Inference Endpoint URL.
    extract_model:
        Model ID to use for extraction.
    request_timeout:
        HTTP request timeout in seconds.

    Examples
    --------
    >>> from silocrawl import SiloCrawl
    >>> sc = SiloCrawl(hf_api_key="hf_...")
    >>>
    >>> # Scrape a page
    >>> result = sc.scrape("https://example.com")
    >>> print(result.markdown)
    >>>
    >>> # Crawl a site
    >>> pages = sc.crawl("https://bbc.com/sport/cricket", max_pages=10)
    >>> for page in pages:
    ...     print(page.metadata.title)
    """

    def __init__(
        self,
        hf_api_key: str | None = None,
        hf_endpoint_url: str | None = None,
        extract_model: str | None = None,
        request_timeout: float | None = None,
    ) -> None:
        self._client = AsyncSiloCrawl(
            hf_api_key=hf_api_key,
            hf_endpoint_url=hf_endpoint_url,
            extract_model=extract_model,
            request_timeout=request_timeout,
        )

    def scrape(
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
            Output formats — any of ``"markdown"``, ``"html"``,
            ``"text"``, ``"links"``. Defaults to ``["markdown"]``.
        render_js:
            Use Playwright to render JavaScript before extracting.
        only_main_content:
            Strip navigation/ads and return only the main body.

        Returns
        -------
        ScrapeResult
            ``.markdown``, ``.html``, ``.text``, ``.links``, ``.metadata``.
        """
        return asyncio.run(
            self._client.scrape(
                url,
                formats=formats,
                render_js=render_js,
                only_main_content=only_main_content,
            )
        )

    def map(self, url: str, *, limit: int = 500) -> list[str]:
        """Discover all URLs on a domain.

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
        return asyncio.run(self._client.map(url, limit=limit))

    def extract(
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
        content:
            Raw text to extract from directly (skips scraping).
        schema:
            JSON Schema describing the structure to extract.
        prompt:
            Optional instruction for the LLM.
        render_js:
            Render JavaScript before scraping.

        Returns
        -------
        dict
            Extracted data conforming to the provided schema.
        """
        return asyncio.run(
            self._client.extract(
                url,
                content=content,
                schema=schema,
                prompt=prompt,
                render_js=render_js,
            )
        )

    def crawl(
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
            Maximum link-follow depth.
        formats:
            Output formats for each page. Defaults to ``["markdown"]``.
        render_js:
            Use Playwright to render JavaScript on every page.
        include_paths:
            Regex patterns — only URLs matching at least one are followed.
        exclude_paths:
            Regex patterns — URLs matching any are skipped.
        allow_external:
            Follow links to external domains.

        Returns
        -------
        list[ScrapeResult]
            One result per successfully crawled page.
        """
        return asyncio.run(
            self._client.crawl(
                url,
                max_pages=max_pages,
                max_depth=max_depth,
                formats=formats,
                render_js=render_js,
                include_paths=include_paths,
                exclude_paths=exclude_paths,
                allow_external=allow_external,
            )
        )
