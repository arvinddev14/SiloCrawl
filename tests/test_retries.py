import httpx
import pytest
from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import DomainStrategy
from app.loop import orchestrator, retries
from app.loop.orchestrator import SCRAPE_STEPS
from app.models.schemas import ScrapeRequest
from app.services import fetcher
from app.services.fetcher import FetchResponse


@pytest.fixture(autouse=True)
def fast_delay(monkeypatch):
    # Don't actually sleep on the browser_delay rung.
    monkeypatch.setattr(retries, "DELAY_RUNG_BACKOFF", 0.0)


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://blocked.test/")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(str(status), request=req, response=resp)


def _ok(url: str) -> FetchResponse:
    return FetchResponse(url, "<html><body>ok</body></html>", 200)


async def _strategy_row(domain: str) -> DomainStrategy | None:
    async with session_scope() as s:
        return (
            await s.execute(select(DomainStrategy).where(DomainStrategy.domain == domain))
        ).scalar_one_or_none()


async def test_static_success_no_escalation(temp_db, monkeypatch):
    calls = {"static": 0, "rendered": 0}

    async def fake_static(url, extra_headers=None):
        calls["static"] += 1
        return _ok(url)

    async def fake_rendered(url, capture_screenshot=False):
        calls["rendered"] += 1
        return _ok(url)

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)
    monkeypatch.setattr(fetcher, "fetch_rendered", fake_rendered)

    resp = await retries.escalating_fetch("https://a.test/")
    assert resp.status_code == 200
    assert calls == {"static": 1, "rendered": 0}
    row = await _strategy_row("a.test")
    assert row.strategy == "static"
    assert row.success_rate == 1.0


async def test_escalates_403_static_to_headers(temp_db, monkeypatch):
    async def fake_static(url, extra_headers=None):
        if extra_headers is None:  # static rung
            raise _http_error(403)
        return _ok(url)  # headers rung succeeds

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)

    resp = await retries.escalating_fetch("https://b.test/")
    assert resp.status_code == 200
    row = await _strategy_row("b.test")
    assert row.strategy == "headers"


async def test_terminal_404_does_not_escalate(temp_db, monkeypatch):
    calls = {"rendered": 0}

    async def fake_static(url, extra_headers=None):
        raise _http_error(404)

    async def fake_rendered(url, capture_screenshot=False):
        calls["rendered"] += 1
        return _ok(url)

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)
    monkeypatch.setattr(fetcher, "fetch_rendered", fake_rendered)

    with pytest.raises(httpx.HTTPStatusError):
        await retries.escalating_fetch("https://c.test/")
    assert calls["rendered"] == 0  # 404 is terminal — never reached the browser
    row = await _strategy_row("c.test")
    assert row.success_rate == 0.0


async def test_all_rungs_fail_reraises_last(temp_db, monkeypatch):
    async def fake_static(url, extra_headers=None):
        raise _http_error(503)

    async def fake_rendered(url, capture_screenshot=False):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)
    monkeypatch.setattr(fetcher, "fetch_rendered", fake_rendered)

    with pytest.raises(httpx.ConnectError):
        await retries.escalating_fetch("https://d.test/")
    row = await _strategy_row("d.test")
    assert row.success_rate == 0.0


async def test_remembered_browser_skips_cheap_rungs(temp_db, monkeypatch):
    async with session_scope() as s:
        s.add(DomainStrategy(domain="e.test", strategy="browser", success_rate=0.9))

    async def fake_static(url, extra_headers=None):
        raise AssertionError("static should be skipped for a remembered browser domain")

    async def fake_rendered(url, capture_screenshot=False):
        return _ok(url)

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)
    monkeypatch.setattr(fetcher, "fetch_rendered", fake_rendered)

    resp = await retries.escalating_fetch("https://e.test/")
    assert resp.status_code == 200


async def test_render_js_starts_at_browser(temp_db, monkeypatch):
    async def fake_static(url, extra_headers=None):
        raise AssertionError("render_js should skip the static rung")

    async def fake_rendered(url, capture_screenshot=False):
        return _ok(url)

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)
    monkeypatch.setattr(fetcher, "fetch_rendered", fake_rendered)

    resp = await retries.escalating_fetch("https://f.test/", render_js=True)
    assert resp.status_code == 200


async def test_orchestrator_scrape_loop_records_strategy(temp_db, monkeypatch):
    monkeypatch.setattr(fetcher.settings, "respect_robots", False)
    monkeypatch.setattr(fetcher.settings, "per_domain_delay", 0.0)

    async def fake_static(url, extra_headers=None):
        return FetchResponse(
            url, "<html><body><article><h1>Hi</h1><p>Body text.</p></article></body></html>", 200
        )

    monkeypatch.setattr(fetcher, "fetch_static", fake_static)

    req = ScrapeRequest(url="https://g.test")
    result = await orchestrator.run(req, steps=SCRAPE_STEPS)
    assert result.metadata is not None
    row = await _strategy_row("g.test")
    assert row is not None
    assert row.strategy == "static"
