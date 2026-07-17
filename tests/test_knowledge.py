import json

from sqlalchemy import func, select

from app.db.base import session_scope
from app.db.models import DomainStrategy, KnowledgeEntity, KnowledgeRelation
from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.loop import memory, orchestrator
from app.models.schemas import ExtractRequest, ExtractResult
from app.services import knowledge

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


async def _count(model) -> int:
    async with session_scope() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def _entities(entity_type=None):
    async with session_scope() as s:
        q = select(KnowledgeEntity)
        if entity_type:
            q = q.where(KnowledgeEntity.entity_type == entity_type)
        return (await s.execute(q)).scalars().all()


# ---------- store primitives ----------

async def test_entity_upsert_is_idempotent(temp_db):
    async with session_scope() as s:
        first = await knowledge.get_or_create_entity(
            s, "page", "https://x.test/p", domain="x.test", data={"a": 1}
        )
        first_id = first.id
    async with session_scope() as s:
        again = await knowledge.get_or_create_entity(
            s, "page", "https://x.test/p", domain="x.test", data={"b": 2}
        )
        assert again.id == first_id
        assert again.data == {"a": 1, "b": 2}
    assert await _count(KnowledgeEntity) == 1


async def test_record_extraction_builds_graph(temp_db):
    await knowledge.record_extraction(
        "https://shop.test/item1", {"title": "Widget", "price": 9}, confidence=0.9
    )
    entities = {(e.entity_type, e.name) for e in await _entities()}
    assert ("domain", "shop.test") in entities
    assert ("page", "https://shop.test/item1") in entities
    assert ("record", "Widget") in entities

    async with session_scope() as s:
        predicates = {
            r.predicate
            for r in (await s.execute(select(KnowledgeRelation))).scalars().all()
        }
    assert predicates == {"part_of", "extracted_from"}


async def test_reextraction_updates_instead_of_duplicating(temp_db):
    for _ in range(2):
        await knowledge.record_extraction(
            "https://shop.test/item1", {"title": "Widget"}, confidence=0.8
        )
    pages = await _entities("page")
    assert len(pages) == 1
    assert pages[0].data["extractions"] == 2
    assert await _count(KnowledgeRelation) == 2  # triples deduped too


# ---------- loop capture ----------

def _fake_stages(monkeypatch, data, source_url="https://k.test/page"):
    async def fake_get_content(req, *, escalate=False):
        return "The Widget is here.", source_url

    async def fake_extract(req, *, escalate=False, content=None, source_url_=None, **kw):
        return ExtractResult(data=data, source_url=source_url)

    monkeypatch.setattr(orchestrator.extractor, "get_content", fake_get_content)
    monkeypatch.setattr(orchestrator.extractor, "extract", fake_extract)


async def test_loop_extract_captures_knowledge(temp_db, monkeypatch):
    _fake_stages(monkeypatch, {"title": "Widget"})
    req = ExtractRequest(content="ignored", schema=SCHEMA)
    await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS)
    assert {e.entity_type for e in await _entities()} == {"domain", "page", "record"}


async def test_failed_verdict_skips_capture(temp_db, monkeypatch):
    class FakeVerifier:  # judges everything unsupported -> verdict "fail"
        async def complete(self, **kw):
            fields = [{"name": "title", "verdict": "unsupported"}]
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="report_verification",
                        arguments=json.dumps({"fields": fields}),
                    )
                ]
            )

    _fake_stages(monkeypatch, {"title": "Nonexistent Thing"})
    monkeypatch.setattr(
        get_router()._registry, "provider_for", lambda spec: FakeVerifier()
    )
    req = ExtractRequest(content="ignored", schema=SCHEMA)
    result = await orchestrator.run(
        req, steps=orchestrator.extract_steps(verify=True)
    )
    assert result.verification["verdict"] == "fail"
    assert await _count(KnowledgeEntity) == 0  # nothing learned from garbage


async def test_capture_failure_never_breaks_request(temp_db, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("db exploded")

    _fake_stages(monkeypatch, {"title": "Widget"})
    monkeypatch.setattr("app.services.knowledge.record_extraction", boom)
    req = ExtractRequest(content="ignored", schema=SCHEMA)
    result = await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS)
    assert result.data == {"title": "Widget"}  # request survived


async def test_plain_extract_records_nothing(client, monkeypatch):
    class FakeProvider:
        async def complete(self, **kw):
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="emit_extracted_data",
                        arguments=json.dumps({"title": "Widget"}),
                    )
                ]
            )

    monkeypatch.setattr(
        get_router()._registry, "provider_for", lambda spec: FakeProvider()
    )
    resp = await client.post(
        "/v1/extract", json={"content": "The Widget is here.", "schema": SCHEMA}
    )
    assert resp.status_code == 200
    assert await _count(KnowledgeEntity) == 0  # knowledge is loop-only


# ---------- read side ----------

async def test_domain_memory_merges_strategy_and_graph(temp_db):
    async with session_scope() as s:
        s.add(DomainStrategy(domain="shop.test", strategy="headers", success_rate=0.75))
    await knowledge.record_extraction("https://shop.test/a", {"title": "A", "price": 1})
    await knowledge.record_extraction("https://shop.test/b", {"title": "B"})

    mem = await memory.domain_memory("shop.test")
    assert mem["strategy"] == {
        "strategy": "headers",
        "success_rate": 0.75,
        "avg_latency_ms": None,
    }
    assert mem["pages_known"] == 2
    assert mem["records_known"] == 2
    assert mem["common_fields"][0] == "title"  # in both pages
    assert mem["last_activity"] is not None


async def test_overview_aggregates_across_domains(temp_db):
    async with session_scope() as s:
        s.add(DomainStrategy(domain="a.test", strategy="browser", success_rate=0.9))
    await knowledge.record_extraction("https://a.test/1", {"title": "One"})
    await knowledge.record_extraction("https://a.test/2", {"title": "Two"})
    await knowledge.record_extraction("https://b.test/1", {"title": "Three"})

    out = await knowledge.overview()
    assert out["entities"] == {"domain": 2, "page": 3, "record": 3}
    assert out["top_domains"][0] == {"domain": "a.test", "pages": 2}
    assert out["strategies"] == [
        {"domain": "a.test", "strategy": "browser", "success_rate": 0.9, "avg_latency_ms": None}
    ]


async def test_overview_route_and_empty_db(client):
    body = (await client.get("/v1/knowledge")).json()
    assert body == {"entities": {}, "top_domains": [], "strategies": []}

    await knowledge.record_extraction("https://a.test/1", {"title": "One"})
    body = (await client.get("/v1/knowledge")).json()
    assert body["entities"]["page"] == 1


async def test_knowledge_route_returns_snapshot(client):
    await knowledge.record_extraction("https://shop.test/a", {"title": "A"})
    resp = await client.get("/v1/knowledge/shop.test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entities"] == {"domain": 1, "page": 1, "record": 1}
    assert body["memory"]["pages_known"] == 1

    empty = (await client.get("/v1/knowledge/never-seen.test")).json()
    assert empty["entities"] == {}
    assert empty["memory"]["pages_known"] == 0
