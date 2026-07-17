import pytest
import respx
from httpx import Response
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Run
from app.loop import orchestrator
from app.loop.orchestrator import EXTRACT_STEPS, SCRAPE_STEPS
from app.loop.state_machine import LoopContext, LoopState, can_transition
from app.models.schemas import (
    ExtractResult,
    PageMetadata,
    ScrapeRequest,
    ScrapeResult,
)
from app.services import fetcher

PAGE = (
    "<html lang='en'><head><title>Hi</title></head>"
    "<body><article><h1>Hello</h1><p>World body text.</p></article></body></html>"
)


def _fake_scrape_result(url="https://example.com/"):
    return ScrapeResult(metadata=PageMetadata(source_url=url), markdown="# Hello")


async def _loop_runs():
    async with get_sessionmaker()() as s:
        return (await s.execute(select(Run).where(Run.kind == "loop"))).scalars().all()


# ---------- state machine ----------

def test_illegal_transition_rejected():
    ctx = LoopContext(request=None, steps=SCRAPE_STEPS)
    ctx.state = LoopState.FETCH
    with pytest.raises(ValueError):
        ctx.advance(LoopState.PLAN)  # backwards is illegal


def test_error_always_reachable():
    assert can_transition(LoopState.FETCH, LoopState.ERROR)
    assert can_transition(LoopState.PLAN, LoopState.ERROR)


# ---------- orchestrator ----------

async def test_scrape_loop_runs_all_states(temp_db, monkeypatch):
    async def fake_scrape(req, *, escalate=False):
        return _fake_scrape_result(str(req.url))

    monkeypatch.setattr(orchestrator.scraper, "scrape", fake_scrape)

    req = ScrapeRequest(url="https://example.com")
    result = await orchestrator.run(req, steps=SCRAPE_STEPS)

    assert result.markdown == "# Hello"
    runs = await _loop_runs()
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert runs[0].meta["path"] == ["plan", "fetch", "done"]
    assert runs[0].meta["final_state"] == "done"


async def test_extract_loop_runs_extract_state(temp_db, monkeypatch):
    async def fake_get_content(req, *, escalate=False):
        return "content", str(req.url)

    async def fake_extract(req, *, escalate=False, content=None, source_url=None, deep=False):
        return ExtractResult(data={"ok": True}, source_url=source_url)

    monkeypatch.setattr(orchestrator.extractor, "get_content", fake_get_content)
    monkeypatch.setattr(orchestrator.extractor, "extract", fake_extract)

    from app.models.schemas import ExtractRequest

    req = ExtractRequest(url="https://example.com", schema={"type": "object"})
    result = await orchestrator.run(req, steps=EXTRACT_STEPS)

    assert result.data == {"ok": True}
    runs = await _loop_runs()
    assert runs[0].meta["path"] == ["plan", "extract", "done"]


async def test_loop_error_transitions_to_error_state(temp_db, monkeypatch):
    async def boom(req, *, escalate=False):
        raise RuntimeError("fetch exploded")

    monkeypatch.setattr(orchestrator.scraper, "scrape", boom)

    req = ScrapeRequest(url="https://example.com")
    with pytest.raises(RuntimeError, match="fetch exploded"):
        await orchestrator.run(req, steps=SCRAPE_STEPS)

    runs = await _loop_runs()
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert runs[0].meta["final_state"] == "error"
    assert runs[0].meta["path"][-1] == "error"


# ---------- route wiring ----------

@pytest.fixture
def no_politeness(monkeypatch):
    monkeypatch.setattr(fetcher.settings, "respect_robots", False)
    monkeypatch.setattr(fetcher.settings, "per_domain_delay", 0.0)


@respx.mock
async def test_scrape_endpoint_loop_true_matches_shape(client, no_politeness):
    respx.get("https://example.com/").mock(return_value=Response(200, html=PAGE))
    resp = await client.post(
        "/v1/scrape", params={"loop": "true"}, json={"url": "https://example.com"}
    )
    assert resp.status_code == 200
    assert "Hello" in resp.json()["markdown"]
    # the loop path recorded its telemetry run
    assert len(await _loop_runs()) == 1


@respx.mock
async def test_scrape_endpoint_loop_false_writes_no_loop_run(client, no_politeness):
    respx.get("https://example.com/").mock(return_value=Response(200, html=PAGE))
    resp = await client.post("/v1/scrape", json={"url": "https://example.com"})
    assert resp.status_code == 200
    assert await _loop_runs() == []  # plain path, no loop orchestration
