from types import SimpleNamespace

from app.core import auth
from app.core.config import get_settings


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        pass

    async def aclose(self):
        pass


def _enable_auth(monkeypatch, keys="test123", limit=0):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "api_keys", keys)
    monkeypatch.setattr(s, "rate_limit_per_minute", limit)


async def test_auth_disabled_by_default(client):
    resp = await client.get("/metrics", params={"hours": 0})
    assert resp.status_code == 200


async def test_missing_key_rejected(client, monkeypatch):
    _enable_auth(monkeypatch)
    assert (await client.get("/metrics")).status_code == 401


async def test_wrong_key_rejected(client, monkeypatch):
    _enable_auth(monkeypatch)
    resp = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_bearer_key_accepted(client, monkeypatch):
    _enable_auth(monkeypatch)
    resp = await client.get(
        "/metrics", params={"hours": 0}, headers={"Authorization": "Bearer test123"}
    )
    assert resp.status_code == 200


async def test_x_api_key_accepted(client, monkeypatch):
    _enable_auth(monkeypatch, keys="k1, k2")
    resp = await client.get("/metrics", params={"hours": 0}, headers={"x-api-key": "k2"})
    assert resp.status_code == 200


async def test_v1_routes_are_protected(client, monkeypatch):
    _enable_auth(monkeypatch)
    resp = await client.post("/v1/scrape", json={"url": "https://example.com"})
    assert resp.status_code == 401


async def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    _enable_auth(monkeypatch, limit=2)
    fake = FakeRedis()
    monkeypatch.setattr(auth, "_client", lambda: fake)
    # freeze time so the fixed window can't roll over mid-test
    monkeypatch.setattr(auth, "time", SimpleNamespace(time=lambda: 1_000_000.0))

    headers = {"Authorization": "Bearer test123"}
    assert (await client.get("/metrics", params={"hours": 0}, headers=headers)).status_code == 200
    assert (await client.get("/metrics", params={"hours": 0}, headers=headers)).status_code == 200
    resp = await client.get("/metrics", headers=headers)
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


async def test_redis_down_fails_open(client, monkeypatch):
    _enable_auth(monkeypatch, limit=5)

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(auth, "_client", boom)
    resp = await client.get(
        "/metrics", params={"hours": 0}, headers={"Authorization": "Bearer test123"}
    )
    assert resp.status_code == 200
