import base64

from app.models.schemas import OutputFormat, ScrapeRequest
from app.services import fetcher, scraper

PNG = b"\x89PNG-fake-bytes"


async def test_screenshot_forces_rendered_path(monkeypatch):
    called = {}

    async def fake_rendered(url, capture_screenshot=False):
        called["rendered"] = True
        called["capture"] = capture_screenshot
        return fetcher.FetchResponse(
            url, "<html><body><p>hi</p></body></html>", 200, screenshot=PNG
        )

    async def fail_static(url):
        raise AssertionError("static path must not be used when a screenshot is requested")

    monkeypatch.setattr(fetcher, "fetch_rendered", fake_rendered)
    monkeypatch.setattr(fetcher, "fetch_static", fail_static)
    # shared Settings instance: skip robots lookups + politeness sleeps in this unit test
    monkeypatch.setattr(fetcher.settings, "respect_robots", False)
    monkeypatch.setattr(fetcher.settings, "per_domain_delay", 0.0)

    req = ScrapeRequest(
        url="https://example.com",
        formats=[OutputFormat.markdown, OutputFormat.screenshot],
    )
    res = await scraper.scrape(req)

    assert called == {"rendered": True, "capture": True}
    assert res.screenshot == base64.b64encode(PNG).decode()
