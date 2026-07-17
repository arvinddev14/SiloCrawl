from app.models.schemas import CrawlRequest, PageMetadata, ScrapeResult
from app.services import crawler

SITE = {
    "https://example.com/": [
        "https://example.com/a",
        "https://example.com/b",
        "https://other.com/x",
    ],
    "https://example.com/a": ["https://example.com/a1", "https://example.com/"],
    "https://example.com/b": ["https://example.com/private/secret"],
    "https://example.com/a1": [],
    "https://example.com/private/secret": [],
}


def _fake_scrape(fail_urls=frozenset()):
    async def scrape(req):
        url = str(req.url)
        if url in fail_urls:
            raise RuntimeError("boom")
        return ScrapeResult(
            metadata=PageMetadata(source_url=url),
            markdown="x",
            links=SITE.get(url, []),
        )

    return scrape


async def test_max_pages_capped(monkeypatch):
    monkeypatch.setattr(crawler.scraper, "scrape", _fake_scrape())
    req = CrawlRequest(url="https://example.com", max_pages=2, max_depth=5)
    results, _ = await crawler.crawl(req)
    assert len(results) <= 2


async def test_max_depth_cutoff(monkeypatch):
    monkeypatch.setattr(crawler.scraper, "scrape", _fake_scrape())
    req = CrawlRequest(url="https://example.com", max_pages=100, max_depth=1)
    results, _ = await crawler.crawl(req)
    urls = {r.metadata.source_url for r in results}
    assert "https://example.com/" in urls
    assert "https://example.com/a" in urls
    assert "https://example.com/a1" not in urls  # depth 2, beyond max_depth


async def test_exclude_paths(monkeypatch):
    monkeypatch.setattr(crawler.scraper, "scrape", _fake_scrape())
    req = CrawlRequest(
        url="https://example.com", max_pages=100, max_depth=5, exclude_paths=["/private"]
    )
    results, _ = await crawler.crawl(req)
    assert not any("/private" in r.metadata.source_url for r in results)


async def test_external_domains_skipped(monkeypatch):
    monkeypatch.setattr(crawler.scraper, "scrape", _fake_scrape())
    req = CrawlRequest(url="https://example.com", max_pages=100, max_depth=5)
    results, _ = await crawler.crawl(req)
    assert not any("other.com" in r.metadata.source_url for r in results)


async def test_failures_recorded(monkeypatch):
    monkeypatch.setattr(
        crawler.scraper, "scrape", _fake_scrape(fail_urls={"https://example.com/a"})
    )
    req = CrawlRequest(url="https://example.com", max_pages=100, max_depth=5)
    _, failures = await crawler.crawl(req)
    assert "https://example.com/a" in {u for u, _ in failures}
