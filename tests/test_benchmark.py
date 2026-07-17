import json

import pytest
from sqlalchemy import select

from app.db.base import get_sessionmaker, session_scope
from app.db.models import Benchmark, Run
from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.loop import benchmark, orchestrator
from app.loop.state_machine import LoopContext, LoopState
from app.models.schemas import ExtractRequest, ExtractResult
from app.services import evaluator

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "author": {"type": "string"}},
}


def _ctx(state=LoopState.DONE, result=None, request=None):
    ctx = LoopContext(request=request, steps=orchestrator.EXTRACT_STEPS)
    ctx.state = state
    ctx.extract_result = result
    return ctx


async def _benchmark_rows():
    async with session_scope() as s:
        return (await s.execute(select(Benchmark))).scalars().all()


# ---------- evaluator ----------

def test_evaluator_full_artifacts():
    req = ExtractRequest(content="x", schema=SCHEMA)
    result = ExtractResult(data={"title": "A", "author": "B"})
    result.verification = {
        "confidence": 0.9,
        "field_coverage": 1.0,
        "evidence_score": 0.8,
    }
    result.repair = {"attempted": True, "repaired_fields": ["author"]}
    result.extraction = {"llm_calls": 3, "chunks": 2}

    m = evaluator.evaluate(_ctx(result=result, request=req), duration_ms=120)
    assert m["success"] == 1.0
    assert m["duration_ms"] == 120.0
    assert m["hallucination_rate"] == 0.2
    assert m["repair_rate"] == 0.5  # 1 of 2 schema fields repaired
    assert m["llm_calls"] == 3.0
    assert m["overall"] == 0.9  # success x confidence


def test_evaluator_minimal_scrape_run():
    m = evaluator.evaluate(_ctx(), duration_ms=50)
    assert m["success"] == 1.0
    assert m["overall"] == 1.0
    assert "confidence" not in m
    assert "repair_rate" not in m


def test_evaluator_failed_run_scores_zero():
    m = evaluator.evaluate(_ctx(state=LoopState.ERROR), duration_ms=10)
    assert m["success"] == 0.0
    assert m["overall"] == 0.0


# ---------- benchmark store ----------

async def test_record_and_summary(temp_db):
    await benchmark.record("r1", {"success": 1.0, "overall": 0.8})
    await benchmark.record("r2", {"success": 0.0, "overall": 0.0})

    rows = await _benchmark_rows()
    assert len(rows) == 4
    assert {r.run_id for r in rows} == {"r1", "r2"}

    out = await benchmark.summary(hours=0)
    metrics = {m["metric"]: m for m in out["metrics"]}
    assert metrics["success"]["avg"] == 0.5
    assert metrics["success"]["count"] == 2
    assert metrics["overall"]["max"] == 0.8
    assert len(out["recent"]) == 4


# ---------- loop capture ----------

def _fake_stages(monkeypatch, fail=False):
    async def fake_get_content(req, *, escalate=False):
        if fail:
            raise RuntimeError("fetch exploded")
        return "The Widget is here.", "https://b.test/p"

    async def fake_extract(req, *, escalate=False, content=None, source_url=None, deep=False):
        return ExtractResult(data={"title": "Widget"}, source_url=source_url)

    monkeypatch.setattr(orchestrator.extractor, "get_content", fake_get_content)
    monkeypatch.setattr(orchestrator.extractor, "extract", fake_extract)


async def test_loop_benchmark_records_rows_tied_to_run(temp_db, monkeypatch):
    _fake_stages(monkeypatch)
    req = ExtractRequest(content="ignored", schema=SCHEMA)
    await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS, benchmark=True)

    rows = await _benchmark_rows()
    values = {r.metric: r.value for r in rows}
    assert values["success"] == 1.0
    assert values["duration_ms"] >= 0

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "loop"))).scalar_one()
    assert all(r.run_id == run.id for r in rows)


async def test_failed_run_still_benchmarks_and_raises(temp_db, monkeypatch):
    _fake_stages(monkeypatch, fail=True)
    req = ExtractRequest(content="ignored", schema=SCHEMA)
    with pytest.raises(RuntimeError, match="fetch exploded"):
        await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS, benchmark=True)

    values = {r.metric: r.value for r in await _benchmark_rows()}
    assert values["success"] == 0.0
    assert values["overall"] == 0.0


async def test_benchmark_off_records_nothing(temp_db, monkeypatch):
    _fake_stages(monkeypatch)
    req = ExtractRequest(content="ignored", schema=SCHEMA)
    await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS)
    assert await _benchmark_rows() == []


# ---------- routes ----------

class FakeProvider:
    async def complete(self, **kw):
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    name="emit_extracted_data",
                    arguments=json.dumps({"title": "Widget", "author": None}),
                )
            ]
        )


async def test_extract_benchmark_flag_implies_loop(client, monkeypatch):
    monkeypatch.setattr(
        get_router()._registry, "provider_for", lambda spec: FakeProvider()
    )
    resp = await client.post(
        "/v1/extract",
        params={"benchmark": "true"},  # no loop= — implied
        json={"content": "The Widget is here.", "schema": SCHEMA},
    )
    assert resp.status_code == 200
    rows = await _benchmark_rows()
    assert {r.metric for r in rows} >= {"success", "duration_ms", "overall"}

    async with get_sessionmaker()() as s:
        loops = (await s.execute(select(Run).where(Run.kind == "loop"))).scalars().all()
    assert len(loops) == 1  # the pipeline was engaged


async def test_plain_extract_no_benchmark_rows(client, monkeypatch):
    monkeypatch.setattr(
        get_router()._registry, "provider_for", lambda spec: FakeProvider()
    )
    resp = await client.post(
        "/v1/extract", json={"content": "The Widget is here.", "schema": SCHEMA}
    )
    assert resp.status_code == 200
    assert await _benchmark_rows() == []


async def test_benchmarks_route(client):
    await benchmark.record("r1", {"success": 1.0})
    resp = await client.get("/v1/benchmarks", params={"hours": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_hours"] == 0
    assert body["metrics"][0]["metric"] == "success"
    assert body["recent"][0]["run_id"] == "r1"
