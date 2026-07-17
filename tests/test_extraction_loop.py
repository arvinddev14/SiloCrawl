import json

from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Run
from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.loop import orchestrator
from app.models.schemas import ExtractRequest
from app.services import extractor

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "author": {"type": "string"}},
}
SCHEMA3 = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "author": {"type": "string"},
        "year": {"type": "integer"},
    },
}

# Two paragraphs, each under an 80-char limit, together over it -> 2 chunks.
P1 = "The book title is The Silent Patient. " + "filler " * 4
P2 = "Alex Michaelides wrote it in 2019. " + "filler " * 4
LONG = f"{P1}\n\n{P2}"


class ChunkFake:
    """Per-chunk answers keyed on what the chunk contains + the tool schema.

    Simulates a model that misses `year` on broad passes but finds it when
    asked for just that field (the focused-retry scenario).
    """

    def __init__(self):
        self.calls = 0
        self.tool_props: list[list[str]] = []

    async def complete(self, **kw):
        self.calls += 1
        user = kw["messages"][1]["content"]
        props = kw["tools"][0]["function"]["parameters"].get("properties") or {}
        self.tool_props.append(sorted(props))
        data = {name: None for name in props}
        if "title" in props and "The Silent Patient" in user:
            data["title"] = "The Silent Patient"
        if "author" in props and "Alex Michaelides" in user:
            data["author"] = "Alex Michaelides"
        if "year" in props and len(props) == 1 and "2019" in user:
            data["year"] = 2019  # only found on the focused retry
        if not props:  # freeform schema
            data = {"summary": "a thriller"}
        return LLMResponse(
            tool_calls=[ToolCall(name="emit_extracted_data", arguments=json.dumps(data))],
            usage={"total_tokens": 5},
        )


def _patch(monkeypatch, provider=None):
    provider = provider or ChunkFake()
    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: provider)
    monkeypatch.setattr(extractor.settings, "extract_content_limit", 80)
    return provider


# ---------- chunker / merge / subschema (pure functions) ----------

def test_chunker_short_content_single_chunk():
    assert extractor._chunks("hello", limit=100, max_chunks=8) == ["hello"]


def test_chunker_splits_on_paragraph_boundaries():
    paras = [f"para{i} " + "x" * 30 for i in range(10)]
    content = "\n\n".join(paras)
    chunks = extractor._chunks(content, limit=90, max_chunks=8)
    assert 1 < len(chunks) <= 8
    assert all(len(c) <= 90 for c in chunks)
    for chunk in chunks:  # no paragraph was broken apart
        assert set(chunk.split("\n\n")) <= set(paras)


def test_chunker_hard_splits_oversized_paragraph():
    chunks = extractor._chunks("y" * 250, limit=100, max_chunks=8)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_merge_first_non_null_wins_and_lists_union():
    merged = extractor._merge_chunk_data(
        [
            {"title": None, "tags": ["a", "b"], "price": 5},
            {"title": "X", "tags": ["b", "c"], "price": 9},
        ]
    )
    assert merged == {"title": "X", "tags": ["a", "b", "c"], "price": 5}


def test_missing_subschema():
    sub = extractor._missing_subschema(SCHEMA, {"title": "X", "author": None})
    assert list(sub["properties"]) == ["author"]
    assert extractor._missing_subschema(SCHEMA, {"title": "X", "author": "Y"}) is None


# ---------- deep extraction ----------

async def test_deep_map_reduce_combines_chunks(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    req = ExtractRequest(content=LONG, schema=SCHEMA)
    result = await extractor.extract(req, deep=True)
    assert result.data["title"] == "The Silent Patient"
    assert result.data["author"] == "Alex Michaelides"
    assert result.extraction["chunks"] == 2
    assert result.extraction["llm_calls"] == 2  # complete after map, no retry
    assert fake.calls == 2


async def test_deep_retries_only_missing_fields(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    req = ExtractRequest(content=LONG, schema=SCHEMA3)
    result = await extractor.extract(req, deep=True)
    assert result.data["year"] == 2019
    assert result.extraction["retried_fields"] == ["year"]
    assert result.extraction["filled_by_retry"] == ["year"]
    # the retry calls carried a sub-schema of just the missing field
    assert ["year"] in fake.tool_props
    # 2 map calls + 2 retry walks (year lives in the second chunk)
    assert result.extraction["llm_calls"] == 4


async def test_plain_path_single_call_and_no_stats(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    req = ExtractRequest(content=LONG, schema=SCHEMA)
    result = await extractor.extract(req)  # deep off — legacy truncation
    assert fake.calls == 1
    assert result.extraction is None


# ---------- freeform schema ----------

async def test_freeform_extraction_without_schema(temp_db, monkeypatch):
    _patch(monkeypatch)
    req = ExtractRequest(content="short text", prompt="Summarize the key facts.")
    result = await extractor.extract(req)
    assert result.data == {"summary": "a thriller"}


async def test_route_accepts_schemaless_request(client, monkeypatch):
    _patch(monkeypatch)
    resp = await client.post("/v1/extract", json={"content": "short text"})
    assert resp.status_code == 200
    assert resp.json()["data"] == {"summary": "a thriller"}


# ---------- loop wiring ----------

async def test_loop_deep_extraction_records_stats(temp_db, monkeypatch):
    _patch(monkeypatch)
    req = ExtractRequest(content=LONG, schema=SCHEMA)
    result = await orchestrator.run(req, steps=orchestrator.EXTRACT_STEPS)
    assert result.extraction["chunks"] == 2

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "loop"))).scalar_one()
    assert run.meta["extraction"]["chunks"] == 2
