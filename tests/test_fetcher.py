from types import SimpleNamespace

import httpx
import pytest
import respx
from httpx import Response

from app.services import fetcher


@pytest.fixture(autouse=True)
def no_politeness(monkeypatch):
    monkeypatch.setattr(fetcher.settings, "respect_robots", False)
    monkeypatch.setattr(fetcher.settings, "per_domain_delay", 0.0)


@respx.mock
async def test_fetch_retries_then_succeeds():
    respx.get("https://example.com/").mock(
        side_effect=[Response(500), Response(200, html="<html><body>ok</body></html>")]
    )
    resp = await fetcher.fetch("https://example.com/")
    assert resp.status_code == 200
    assert "ok" in resp.html


def _state_for(retry_after: str):
    resp = httpx.Response(503, headers={"retry-after": retry_after})
    exc = httpx.HTTPStatusError(
        "x", request=httpx.Request("GET", "https://e.com/"), response=resp
    )
    return SimpleNamespace(
        outcome=SimpleNamespace(exception=lambda: exc), attempt_number=1
    )


def test_wait_honors_retry_after_header():
    w = fetcher._wait_retry_after(multiplier=0.5, max=8)
    assert w(_state_for("7")) == 7.0


def test_wait_caps_retry_after_at_30():
    w = fetcher._wait_retry_after(multiplier=0.5, max=8)
    assert w(_state_for("120")) == 30.0
