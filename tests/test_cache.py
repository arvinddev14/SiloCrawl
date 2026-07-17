import pytest

from app.models.schemas import PageMetadata, ScrapeRequest, ScrapeResult
from app.services import cache


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def aclose(self):
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(cache, "_client", lambda: fr)
    return fr


def _req(**kw) -> ScrapeRequest:
    return ScrapeRequest(url="https://example.com", **kw)


def _result() -> ScrapeResult:
    return ScrapeResult(
        metadata=PageMetadata(source_url="https://example.com"), markdown="hello"
    )


async def test_cache_disabled_by_default(fake_redis):
    await cache.set(_req(), _result())
    assert fake_redis.store == {}
    assert await cache.get(_req()) is None


async def test_roundtrip_when_enabled(fake_redis, monkeypatch):
    monkeypatch.setattr(cache.settings, "scrape_cache_ttl", 60)
    await cache.set(_req(), _result())
    got = await cache.get(_req())
    assert got is not None
    assert got.markdown == "hello"


async def test_key_varies_with_options(fake_redis, monkeypatch):
    monkeypatch.setattr(cache.settings, "scrape_cache_ttl", 60)
    await cache.set(_req(), _result())
    assert await cache.get(_req(render_js=True)) is None


async def test_redis_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(cache.settings, "scrape_cache_ttl", 60)

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(cache, "_client", boom)
    assert await cache.get(_req()) is None
    await cache.set(_req(), _result())  # must not raise
