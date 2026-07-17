import pytest
from sqlalchemy import select

from app.core import telemetry
from app.core.config import get_settings
from app.db.base import get_sessionmaker
from app.db.metrics import collect_metrics
from app.db.models import Run, TelemetryEvent
from app.llm import get_router
from app.llm.base import LLMResponse


async def test_track_success_writes_run(temp_db):
    async with telemetry.track("scrape", url="https://example.com") as run:
        run.confidence = 0.9
    async with get_sessionmaker()() as s:
        row = (await s.execute(select(Run))).scalar_one()
    assert row.kind == "scrape"
    assert row.status == "ok"
    assert row.url == "https://example.com"
    assert row.confidence == 0.9
    assert row.duration_ms >= 0


async def test_track_error_writes_event_and_reraises(temp_db):
    with pytest.raises(ValueError):
        async with telemetry.track("scrape"):
            raise ValueError("boom")
    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run))).scalar_one()
        event = (await s.execute(select(TelemetryEvent))).scalar_one()
    assert run.status == "error"
    assert event.run_id == run.id
    assert "boom" in event.message


async def test_track_disabled_writes_nothing(temp_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "telemetry_enabled", False)
    async with telemetry.track("scrape"):
        pass
    async with get_sessionmaker()() as s:
        assert (await s.execute(select(Run))).first() is None


async def test_router_records_llm_usage(temp_db, monkeypatch):
    class FakeProvider:
        async def complete(self, **kw):
            return LLMResponse(text="hi", usage={"total_tokens": 42})

    router = get_router()
    monkeypatch.setattr(router._registry, "provider_for", lambda spec: FakeProvider())

    resp = await router.complete("extractor", messages=[{"role": "user", "content": "x"}])
    assert resp.text == "hi"

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "llm"))).scalar_one()
    assert run.agent == "extractor"
    assert run.model == "openai/gpt-oss-120b"
    assert run.tokens == 42
    assert run.status == "ok"


async def test_collect_metrics_aggregates(temp_db):
    async with telemetry.track("scrape", url="https://a.com"):
        pass
    with pytest.raises(RuntimeError):
        async with telemetry.track("map"):
            raise RuntimeError("x")

    m = await collect_metrics(hours=0)
    counts = {(r["kind"], r["status"]): r["count"] for r in m["runs"]}
    assert counts[("scrape", "ok")] == 1
    assert counts[("map", "error")] == 1
    assert m["window_hours"] == 0
