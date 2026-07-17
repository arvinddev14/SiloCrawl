import json

from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Run
from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.loop import confidence, orchestrator
from app.models.schemas import ExtractRequest
from app.services import verifier

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "author": {"type": "string"}},
}
CONTENT = "The Silent Patient is a thriller written by Alex Michaelides in 2019."


def _tool_response(fields):
    return LLMResponse(
        tool_calls=[
            ToolCall(name="report_verification", arguments=json.dumps({"fields": fields}))
        ],
        usage={"total_tokens": 7},
    )


class RoutedFake:
    """Answers both the extractor and the verifier agents, keyed on tool name."""

    def __init__(self, data, fields):
        self.data = data
        self.fields = fields
        self.verifier_calls = 0

    async def complete(self, **kw):
        tool = kw["tools"][0]["function"]["name"]
        if tool == "emit_extracted_data":
            return LLMResponse(
                tool_calls=[ToolCall(name=tool, arguments=json.dumps(self.data))],
                usage={"total_tokens": 5},
            )
        self.verifier_calls += 1
        return _tool_response(self.fields)


def _patch_router(monkeypatch, provider):
    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: provider)
    return provider


# ---------- deterministic scoring ----------

def test_schema_invalid_gates_confidence():
    good = confidence.assess({"title": "The Silent Patient"}, SCHEMA, CONTENT)
    bad = confidence.assess({"title": 123}, SCHEMA, CONTENT)
    assert good.schema_valid and not bad.schema_valid
    assert bad.confidence < good.confidence


def test_evidence_flags_hallucinated_value():
    det = confidence.assess({"title": "Gone Girl"}, SCHEMA, CONTENT)
    assert det.evidence_score == 0.0
    assert "title" in det.unsupported_fields


def test_full_coverage_and_evidence_scores_high():
    det = confidence.assess(
        {"title": "The Silent Patient", "author": "Alex Michaelides"}, SCHEMA, CONTENT
    )
    assert det.schema_valid
    assert det.field_coverage == 1.0
    assert det.evidence_score == 1.0
    assert det.confidence == 1.0


# ---------- verification (LLM layer mocked) ----------

async def test_verify_pass(temp_db, monkeypatch):
    class FakeProvider:
        async def complete(self, **kw):
            return _tool_response(
                [{"name": "title", "verdict": "supported"},
                 {"name": "author", "verdict": "supported"}]
            )

    _patch_router(monkeypatch, FakeProvider())
    report = await verifier.verify(
        SCHEMA, {"title": "The Silent Patient", "author": "Alex Michaelides"}, CONTENT
    )
    assert report.verdict == "pass"
    assert report.confidence == 1.0
    assert report.llm_checked


async def test_llm_unsupported_lowers_confidence(temp_db, monkeypatch):
    class FakeProvider:
        async def complete(self, **kw):
            return _tool_response(
                [{"name": "title", "verdict": "supported"},
                 {"name": "author", "verdict": "unsupported"}]
            )

    _patch_router(monkeypatch, FakeProvider())
    report = await verifier.verify(
        SCHEMA, {"title": "The Silent Patient", "author": "Alex Michaelides"}, CONTENT
    )
    # det = 1.0, llm = 0.5 -> 0.7*1.0 + 0.3*0.5 = 0.85, but unsupported -> warn
    assert report.confidence == 0.85
    assert report.unsupported_fields == ["author"]
    assert report.verdict == "warn"


async def test_llm_failure_degrades_to_deterministic(temp_db, monkeypatch):
    class Boom:
        async def complete(self, **kw):
            raise RuntimeError("endpoint down")

    _patch_router(monkeypatch, Boom())
    report = await verifier.verify(SCHEMA, {"title": "The Silent Patient"}, CONTENT)
    assert not report.llm_checked
    assert report.confidence > 0  # deterministic score still stands


# ---------- route wiring ----------

async def test_extract_verify_true_returns_confidence(client, monkeypatch):
    fake = _patch_router(
        monkeypatch,
        RoutedFake(
            data={"title": "The Silent Patient", "author": "Alex Michaelides"},
            fields=[{"name": "title", "verdict": "supported"},
                    {"name": "author", "verdict": "supported"}],
        ),
    )
    resp = await client.post(
        "/v1/extract",
        params={"verify": "true"},
        json={"content": CONTENT, "schema": SCHEMA},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confidence"] == 1.0
    assert body["verification"]["verdict"] == "pass"
    assert fake.verifier_calls == 1

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "extract"))).scalar_one()
    assert run.confidence == 1.0


async def test_extract_without_verify_unchanged(client, monkeypatch):
    fake = _patch_router(
        monkeypatch,
        RoutedFake(data={"title": "The Silent Patient"}, fields=[]),
    )
    resp = await client.post("/v1/extract", json={"content": CONTENT, "schema": SCHEMA})
    assert resp.status_code == 200
    body = resp.json()
    assert body["confidence"] is None
    assert body["verification"] is None
    assert fake.verifier_calls == 0  # verifier agent never invoked


# ---------- loop pipeline ----------

async def test_loop_with_verify_visits_verify_state(temp_db, monkeypatch):
    _patch_router(
        monkeypatch,
        RoutedFake(
            data={"title": "The Silent Patient", "author": "Alex Michaelides"},
            fields=[{"name": "title", "verdict": "supported"},
                    {"name": "author", "verdict": "supported"}],
        ),
    )
    req = ExtractRequest(content=CONTENT, schema=SCHEMA)
    result = await orchestrator.run(req, steps=orchestrator.extract_steps(verify=True))
    assert result.confidence == 1.0

    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "loop"))).scalar_one()
    assert run.meta["path"] == ["plan", "extract", "verify", "done"]
    assert run.confidence == 1.0
