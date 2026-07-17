import json

import pytest
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Run
from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.loop import orchestrator
from app.models.schemas import ExtractRequest
from app.services import extractor, repair

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "author": {"type": "string"}},
}
CONTENT = "The Silent Patient is a thriller written by Alex Michaelides in 2019."
GOOD = {"title": "The Silent Patient", "author": "Alex Michaelides"}


def _tool(name, payload):
    return LLMResponse(
        tool_calls=[ToolCall(name=name, arguments=payload)], usage={"total_tokens": 5}
    )


class RoutedFake:
    """Answers extractor / verifier / repair agents, keyed on the tool name."""

    def __init__(self, extract_args, repaired=None, verdicts=None):
        self.extract_args = extract_args  # raw string handed back as tool arguments
        self.repaired = repaired or {}
        self.verdicts = verdicts or []
        self.calls = {"extract": 0, "verify": 0, "repair": 0}

    async def complete(self, **kw):
        tool = kw["tools"][0]["function"]["name"]
        if tool == "emit_extracted_data":
            self.calls["extract"] += 1
            return _tool(tool, self.extract_args)
        if tool == "report_verification":
            self.calls["verify"] += 1
            return _tool(tool, json.dumps({"fields": self.verdicts}))
        self.calls["repair"] += 1
        return _tool(tool, json.dumps(self.repaired))


def _patch_router(monkeypatch, provider):
    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: provider)
    return provider


# ---------- deterministic JSON salvage ----------

def test_salvage_fixes_fences_and_trailing_commas():
    raw = '```json\n{"title": "The Silent Patient", "author": null,}\n```'
    assert repair.salvage_json(raw) == {"title": "The Silent Patient", "author": None}


def test_salvage_slices_outer_object():
    raw = 'Here is the data: {"title": "X"} hope that helps!'
    assert repair.salvage_json(raw) == {"title": "X"}


def test_salvage_gives_up_on_garbage():
    assert repair.salvage_json("not json at all") is None


# ---------- typed parse error ----------

async def test_extractor_raises_typed_parse_error(temp_db, monkeypatch):
    _patch_router(monkeypatch, RoutedFake(extract_args="{{{definitely broken"))
    with pytest.raises(extractor.ExtractionParseError) as exc:
        await extractor.extract(ExtractRequest(content=CONTENT, schema=SCHEMA))
    assert exc.value.raw == "{{{definitely broken"


async def test_repair_json_llm_fallback(temp_db, monkeypatch):
    fake = _patch_router(monkeypatch, RoutedFake(extract_args="", repaired=GOOD))
    data, used_llm = await repair.repair_json("garbage beyond salvage", SCHEMA)
    assert data == GOOD
    assert used_llm
    assert fake.calls["repair"] == 1


async def test_repair_json_deterministic_skips_llm(temp_db, monkeypatch):
    fake = _patch_router(monkeypatch, RoutedFake(extract_args=""))
    data, used_llm = await repair.repair_json('{"title": "X",}', SCHEMA)
    assert data == {"title": "X"}
    assert not used_llm
    assert fake.calls["repair"] == 0


# ---------- targeted repair + merge ----------

async def test_missing_field_repaired_and_merge_keeps_good_fields(temp_db, monkeypatch):
    # Repair agent tries to change title too — the merge must ignore that.
    fake = _patch_router(
        monkeypatch,
        RoutedFake(extract_args="", repaired={"title": "WRONG", "author": "Alex Michaelides"}),
    )
    data, info = await repair.repair_result(
        {"title": "The Silent Patient", "author": None}, SCHEMA, CONTENT
    )
    assert data == GOOD  # author filled, title untouched
    assert info["attempted"]
    assert info["repaired_fields"] == ["author"]
    assert fake.calls["repair"] == 1


async def test_type_mismatch_repaired(temp_db, monkeypatch):
    _patch_router(
        monkeypatch,
        RoutedFake(extract_args="", repaired={"title": "The Silent Patient", "author": "Alex Michaelides"}),
    )
    data, info = await repair.repair_result({"title": 2019, "author": "Alex Michaelides"}, SCHEMA, CONTENT)
    assert data["title"] == "The Silent Patient"
    assert "title" in info["repaired_fields"]


async def test_clean_extraction_is_a_noop(temp_db, monkeypatch):
    fake = _patch_router(monkeypatch, RoutedFake(extract_args=""))
    data, info = await repair.repair_result(GOOD, SCHEMA, CONTENT)
    assert data == GOOD
    assert not info["attempted"]
    assert fake.calls["repair"] == 0


# ---------- route wiring ----------

async def test_extract_repair_true_returns_repair_block(client, monkeypatch):
    fake = _patch_router(
        monkeypatch,
        RoutedFake(
            extract_args=json.dumps({"title": "The Silent Patient", "author": None}),
            repaired={"author": "Alex Michaelides"},
        ),
    )
    resp = await client.post(
        "/v1/extract", params={"repair": "true"}, json={"content": CONTENT, "schema": SCHEMA}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == GOOD
    assert body["repair"]["attempted"] is True
    assert body["repair"]["repaired_fields"] == ["author"]
    assert fake.calls["repair"] == 1


async def test_extract_without_repair_flag_unchanged(client, monkeypatch):
    fake = _patch_router(monkeypatch, RoutedFake(extract_args=json.dumps(GOOD)))
    resp = await client.post("/v1/extract", json={"content": CONTENT, "schema": SCHEMA})
    assert resp.status_code == 200
    assert resp.json()["repair"] is None
    assert fake.calls["repair"] == 0


# ---------- loop pipeline ----------

async def test_loop_verify_repair_full_path(temp_db, monkeypatch):
    _patch_router(
        monkeypatch,
        RoutedFake(
            extract_args=json.dumps({"title": "The Silent Patient", "author": None}),
            repaired={"author": "Alex Michaelides"},
            verdicts=[{"name": "title", "verdict": "supported"},
                      {"name": "author", "verdict": "not_found"}],
        ),
    )
    req = ExtractRequest(content=CONTENT, schema=SCHEMA)
    result = await orchestrator.run(
        req, steps=orchestrator.extract_steps(verify=True, repair=True)
    )
    assert result.data == GOOD
    assert result.repair["repaired_fields"] == ["author"]
    assert result.confidence == 1.0  # re-verified after the repair

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "loop"))).scalar_one()
    assert run.meta["path"] == ["plan", "extract", "verify", "repair", "done"]


async def test_loop_parse_error_salvaged_when_repair_on(temp_db, monkeypatch):
    _patch_router(
        monkeypatch,
        RoutedFake(extract_args='```json\n{"title": "The Silent Patient", "author": "Alex Michaelides",}\n```'),
    )
    req = ExtractRequest(content=CONTENT, schema=SCHEMA)
    result = await orchestrator.run(
        req, steps=orchestrator.extract_steps(repair=True)
    )
    assert result.data == GOOD
    assert result.repair["parse_repaired"] is True
