"""SiloCrawl — LLM-powered web scraping toolkit.

Quick start
-----------
>>> from silocrawl import SiloCrawl
>>>
>>> sc = SiloCrawl(hf_api_key="hf_...")
>>>
>>> # Scrape a page to Markdown
>>> result = sc.scrape("https://example.com")
>>> print(result.markdown)
>>>
>>> # Discover all URLs on a domain
>>> urls = sc.map("https://example.com")
>>>
>>> # Extract structured data with an LLM
>>> data = sc.extract(
...     "https://example.com",
...     schema={"type": "object", "properties": {"title": {"type": "string"}}},
... )
>>>
>>> # Crawl an entire site
>>> pages = sc.crawl("https://example.com", max_pages=20)
>>> for page in pages:
...     print(page.metadata.title, page.metadata.source_url)
"""

from silocrawl._async import AsyncSiloCrawl
from silocrawl.client import SiloCrawl

__version__ = "0.1.0"
__all__ = ["SiloCrawl", "AsyncSiloCrawl"]
