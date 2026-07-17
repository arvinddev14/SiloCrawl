import json

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import Run
from app.llm import get_router
from app.llm.base import LLMResponse, ModelSpec, ToolCall
from app.loop import orchestrator
from app.loop.orchestrator import EXTRACT_STEPS, SCRAPE_STEPS
from app.models.schemas import ExtractRequest, ScrapeRequest
from app.services import planner

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}
GENERATED = {"type": "object", "properties": {"book_title": {"type": "string"}}}
MEMORY = {"strategy": {"strategy": "browser", "success_rate": 0.9}, "pages_known": 3}


# ---------- deterministic plan ----------

def test_plan_url_with_user_schema():
    req = ExtractRequest(url="https://a.test/x", schema=SCHEMA)
    plan = planner.build_plan(req, MEMORY, EXTRACT_STEPS)
    assert plan["input_type"] == "url"
    assert plan["fetch"]["predicted_strategy"] == "browser"
    assert plan["extraction"]["schema_source"] == "user"


def test_plan_estimates_chunks_and_calls(monkeypatch):
    monkeypatch.setattr(get_settings(), "extract_content_limit", 100)
    req = ExtractRequest(content="x" * 250, schema=SCHEMA)
    steps = orchestrator.extract_steps(verify=True, repair=True)
    plan = planner.build_plan(req, None, steps)
    assert plan["extraction"]["estimated_chunks"] == 3
    # 3 chunk calls + verify + repair stages
    assert plan["estimated_llm_calls"] == 5
    assert plan["estimated_tokens"] == 250 // 4


def test_scrape_plan_has_no_extraction_block():
    req = ScrapeRequest(url="https://a.test/")
    plan = planner.build_plan(req, None, SCRAPE_STEPS)
    assert plan["input_type"] == "url"
    assert "extraction" not in plan
    assert plan["fetch"]["predicted_strategy"] is None


# ---------- schema generation via the loop ----------

class PlannerFake:
    """Answers planner (emit_schema) and extractor (emit_extracted_data)."""

    def __init__(self, schema_result=GENERATED, fail_schema=False):
        self.schema_result = schema_result
        self.fail_schema = fail_schema
        self.schema_calls = 0
        self.extract_params: dict | None = None

    async def complete(self, **kw):
        tool = kw["tools"][0]["function"]["name"]
        if tool == "emit_schema":
            self.schema_calls += 1
            if self.fail_schema:
                raise RuntimeError("planner endpoint down")
            return LLMResponse(
                tool_calls=[
                    ToolCall(name=tool, arguments=json.dumps({"schema": self.schema_result}))
                ]
            )
        self.extract_params = kw["tools"][0]["function"]["parameters"]
        return LLMResponse(
            tool_calls=[
                ToolCall(name=tool, arguments=json.dumps({"book_title": "The Silent Patient"}))
            ]
        )


def _patch(monkeypatch, provider):
    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: provider)
    return provider


async def _loop_run_meta():
    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "loop"))).scalar_one()
    return run.meta


async def test_generated_schema_reaches_extractor(temp_db, monkeypatch):
    fake = _patch(monkeypatch, PlannerFake())
    req = ExtractRequest(content="The Silent Patient by Alex.", prompt="get the book title")
    result = await orchestrator.run(req, steps=EXTRACT_STEPS)
    assert fake.schema_calls == 1
    assert fake.extract_params == GENERATED  # the drafted schema was used
    assert result.data == {"book_title": "The Silent Patient"}

    meta = await _loop_run_meta()
    assert meta["plan"]["extraction"]["schema_source"] == "generated"


async def test_generation_failure_falls_back_to_freeform(temp_db, monkeypatch):
    fake = _patch(monkeypatch, PlannerFake(fail_schema=True))
    req = ExtractRequest(content="The Silent Patient by Alex.", prompt="get the book title")
    result = await orchestrator.run(req, steps=EXTRACT_STEPS)
    assert result.data  # extraction still ran (freeform)
    assert req.json_schema is None  # nothing was applied
    assert fake.extract_params.get("additionalProperties") is True  # freeform tool

    meta = await _loop_run_meta()
    assert meta["plan"]["extraction"]["schema_source"] == "freeform"


async def test_user_schema_never_calls_planner(temp_db, monkeypatch):
    fake = _patch(monkeypatch, PlannerFake())
    req = ExtractRequest(content="The Silent Patient.", schema=SCHEMA, prompt="extract")
    await orchestrator.run(req, steps=EXTRACT_STEPS)
    assert fake.schema_calls == 0

    meta = await _loop_run_meta()
    assert meta["plan"]["extraction"]["schema_source"] == "user"


# ---------- router model override ----------

def _two_model_config():
    def spec(alias, model):
        return ModelSpec(
            alias=alias, provider="openai_compat", model=model,
            endpoint="http://x", api_key="k",
        )

    return (
        {"default": "a", "extractor": "a"},
        {"a": spec("a", "model-a"), "b": spec("b", "model-b")},
    )


async def test_router_model_override(temp_db, monkeypatch):
    class Fake:
        async def complete(self, **kw):
            return LLMResponse(text="ok", usage={"total_tokens": 3})

    monkeypatch.setattr("app.llm.registry.load_config", _two_model_config)
    router = get_router()
    monkeypatch.setattr(router._registry, "provider_for", lambda spec: Fake())

    await router.complete("extractor", model="b", messages=[{"role": "user", "content": "x"}])
    async with get_sessionmaker()() as s:
        run = (await s.execute(select(Run).where(Run.kind == "llm"))).scalar_one()
    assert run.model == "model-b"  # override won over the agent's default alias


async def test_router_unknown_override_raises(temp_db, monkeypatch):
    monkeypatch.setattr("app.llm.registry.load_config", _two_model_config)
    with pytest.raises(KeyError, match="not defined"):
        await get_router().complete(
            "extractor", model="nope", messages=[{"role": "user", "content": "x"}]
        )
