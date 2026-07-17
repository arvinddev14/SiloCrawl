from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Run
from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.loop import orchestrator, prompts
from app.models.schemas import ExtractRequest, ExtractResult
from app.services import extractor, knowledge

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


# ---------- prompt store ----------

async def test_get_prompt_seeds_v1_from_fallback(temp_db):
    assert await prompts.get_prompt("extractor", "system", "FALLBACK") == "FALLBACK"
    rows = await prompts.list_prompts("extractor")
    assert len(rows) == 1
    assert (rows[0]["version"], rows[0]["active"], rows[0]["template"]) == (1, True, "FALLBACK")
    # second call reads the seeded row — the new fallback is ignored
    assert await prompts.get_prompt("extractor", "system", "DIFFERENT") == "FALLBACK"
    assert len(await prompts.list_prompts("extractor")) == 1


async def test_set_prompt_publishes_new_active_version(temp_db):
    await prompts.get_prompt("a", "system", "v1 text")
    out = await prompts.set_prompt("a", "system", "v2 text")
    assert out["version"] == 2
    assert await prompts.get_prompt("a", "system", "ignored") == "v2 text"
    states = {(p["version"], p["active"]) for p in await prompts.list_prompts("a")}
    assert states == {(1, False), (2, True)}


async def test_activate_rolls_back(temp_db):
    await prompts.get_prompt("a", "system", "v1 text")
    await prompts.set_prompt("a", "system", "v2 text")
    assert await prompts.activate("a", "system", 1) is True
    assert await prompts.get_prompt("a", "system", "ignored") == "v1 text"
    assert await prompts.activate("a", "system", 99) is False


async def test_db_failure_returns_fallback(temp_db, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(prompts, "session_scope", boom)
    assert await prompts.get_prompt("a", "system", "SAFE") == "SAFE"


# ---------- agents actually use the store ----------

async def test_extractor_uses_published_prompt(temp_db, monkeypatch):
    seen = {}

    class Fake:
        async def complete(self, **kw):
            seen["system"] = kw["messages"][0]["content"]
            return LLMResponse(
                tool_calls=[ToolCall(name="emit_extracted_data", arguments="{}")]
            )

    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: Fake())
    await prompts.set_prompt("extractor", "system", "You are extractor v2.")
    await extractor.extract(ExtractRequest(content="x", schema=SCHEMA))
    assert seen["system"] == "You are extractor v2."


async def test_extractor_default_prompt_unchanged(temp_db, monkeypatch):
    seen = {}

    class Fake:
        async def complete(self, **kw):
            seen["system"] = kw["messages"][0]["content"]
            return LLMResponse(
                tool_calls=[ToolCall(name="emit_extracted_data", arguments="{}")]
            )

    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: Fake())
    await extractor.extract(ExtractRequest(content="x", schema=SCHEMA))
    assert seen["system"] == extractor.SYSTEM  # seeded v1 == the constant


# ---------- management API ----------

async def test_prompt_routes(client):
    resp = await client.put("/v1/prompts/extractor/system", json={"template": "T1"})
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    resp = await client.put("/v1/prompts/extractor/system", json={"template": "T2"})
    assert resp.json()["version"] == 2

    listing = (await client.get("/v1/prompts", params={"agent": "extractor"})).json()
    assert [p["version"] for p in listing["prompts"]] == [1, 2]

    resp = await client.post(
        "/v1/prompts/extractor/system/activate", params={"version": 1}
    )
    assert resp.status_code == 200
    assert await prompts.get_prompt("extractor", "system", "ignored") == "T1"

    resp = await client.post(
        "/v1/prompts/extractor/system/activate", params={"version": 9}
    )
    assert resp.status_code == 404


# ---------- PLAN stage surfaces domain memory ----------

async def test_plan_stage_loads_domain_memory(temp_db, monkeypatch):
    await knowledge.record_extraction("https://k.test/a", {"title": "A"})

    async def fake_get_content(req, *, escalate=False):
        return "content", "https://k.test/a"

    async def fake_extract(req, *, escalate=False, content=None, source_url=None, deep=False):
        return ExtractResult(data={"title": "A"}, source_url="https://k.test/a")

    monkeypatch.setattr(orchestrator.extractor, "get_content", fake_get_content)
    monkeypatch.setattr(orchestrator.extractor, "extract", fake_extract)

    req = ExtractRequest(url="https://k.test/a", schema=SCHEMA)
    await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS)

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "loop"))).scalar_one()
    assert run.meta["memory"]["domain"] == "k.test"
    assert run.meta["memory"]["pages_known"] == 1
