import pytest
import respx
from httpx import Response

from app.models.schemas import CrawlJob, CrawlStatus
from app.services import crawl_runner, fetcher, jobstore, robots

PAGE = (
    "<html lang='en'><head><title>Hi</title>"
    "<meta name='description' content='A page.'></head>"
    "<body><article><h1>Hello</h1><p>World body text goes here.</p></article></body></html>"
)


@pytest.fixture
def no_politeness(monkeypatch):
    # Patch the module-bound settings the service layer actually holds.
    monkeypatch.setattr(fetcher.settings, "respect_robots", False)
    monkeypatch.setattr(fetcher.settings, "per_domain_delay", 0.0)


@respx.mock
async def test_scrape_happy_path(client, no_politeness):
    respx.get("https://example.com/").mock(return_value=Response(200, html=PAGE))
    resp = await client.post(
        "/v1/scrape", json={"url": "https://example.com", "formats": ["markdown"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "Hello" in body["markdown"]
    assert body["metadata"]["title"] == "Hi"


async def test_root_redirects_to_docs(client):
    resp = await client.get("/")
    assert resp.status_code == 307
    assert resp.headers["location"] == "/docs"


async def test_scrape_invalid_url_returns_422(client):
    resp = await client.post("/v1/scrape", json={"url": "not-a-url"})
    assert resp.status_code == 422


@respx.mock
async def test_scrape_robots_disallowed_returns_403(client, monkeypatch):
    robots._cache.clear()
    monkeypatch.setattr(fetcher.settings, "respect_robots", True)
    monkeypatch.setattr(fetcher.settings, "per_domain_delay", 0.0)
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /\n")
    )
    resp = await client.post(
        "/v1/scrape", json={"url": "https://example.com", "formats": ["markdown"]}
    )
    assert resp.status_code == 403
    robots._cache.clear()


async def test_extract_requires_url_or_content(client):
    resp = await client.post("/v1/extract", json={"schema": {"type": "object"}})
    assert resp.status_code == 400


@respx.mock
async def test_map_discovers_links(client, no_politeness):
    respx.get("https://example.com/sitemap.xml").mock(return_value=Response(404))
    respx.get("https://example.com/sitemap_index.xml").mock(return_value=Response(404))
    respx.get("https://example.com/").mock(
        return_value=Response(
            200,
            html="<html><body><a href='/about'>About</a>"
            "<a href='https://example.com/contact'>Contact</a></body></html>",
        )
    )
    resp = await client.post("/v1/map", json={"url": "https://example.com"})
    assert resp.status_code == 200
    links = resp.json()["links"]
    assert "https://example.com/about" in links


async def test_crawl_status_unknown_returns_404(client):
    resp = await client.get("/v1/crawl/does-not-exist")
    assert resp.status_code == 404


async def test_crawl_status_returns_persisted_job(client):
    await jobstore.save(
        CrawlJob(id="j1", status=CrawlStatus.completed, total=1, completed=1),
        url="https://example.com",
    )
    resp = await client.get("/v1/crawl/j1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "j1"


async def test_crawl_start_returns_queued_and_launches(client, monkeypatch):
    started: list[str] = []

    def _fake_start(job_id, req):
        started.append(job_id)  # don't spawn a real crawl in the test

    monkeypatch.setattr(crawl_runner, "start", _fake_start)
    resp = await client.post("/v1/crawl", json={"url": "https://example.com"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert started == [body["id"]]
    # the queued job is immediately persisted and pollable
    got = await client.get(f"/v1/crawl/{body['id']}")
    assert got.status_code == 200


async def test_crawl_runner_persists_completion(temp_db, monkeypatch):
    from app.models.schemas import CrawlRequest, PageMetadata, ScrapeResult

    async def _fake_crawl(req, on_progress=None):
        page = ScrapeResult(metadata=PageMetadata(source_url=str(req.url)))
        if on_progress:
            on_progress(1, 1, page)
        return [page], []

    monkeypatch.setattr(crawl_runner.crawler, "crawl", _fake_crawl)
    await jobstore.create("run1", url="https://example.com")
    await crawl_runner.run_job("run1", CrawlRequest(url="https://example.com"))

    job = await jobstore.get("run1")
    assert job.status == CrawlStatus.completed
    assert job.completed == 1
    assert len(job.data) == 1
