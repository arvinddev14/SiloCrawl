import json

from sqlalchemy import select

from app.core.config import get_settings
from app.db.base import get_sessionmaker, session_scope
from app.db.models import Benchmark, Run
from app.llm import get_router
from app.llm.base import LLMResponse, ModelSpec, ToolCall
from app.llm.overrides import use_models
from app.loop import experiments
from app.models.schemas import ExtractRequest

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}
CONTENT = "The Silent Patient is a thriller by Alex Michaelides."
TASK = ExtractRequest(content=CONTENT, schema=SCHEMA)


def _spec(alias: str, model: str) -> ModelSpec:
    return ModelSpec(
        alias=alias, provider="openai_compat", model=model,
        endpoint="http://x", api_key="k",
    )


def _config():
    return (
        {"default": "a"},
        {"a": _spec("a", "model-a"), "b": _spec("b", "model-b"), "b2": _spec("b2", "model-b")},
    )


class QualityFake:
    """model-a extracts poorly (misses the field); model-b extracts well.
    Also answers the verifier with evidence-based verdicts."""

    def __init__(self, fail_model: str | None = None):
        self.fail_model = fail_model
        self.models_seen: list[str] = []

    async def complete(self, *, model, messages, tools=None, **kw):
        self.models_seen.append(model)
        tool = tools[0]["function"]["name"] if tools else None
        if tool == "emit_extracted_data":
            if model == self.fail_model:
                raise RuntimeError("candidate endpoint down")
            data = (
                {"title": "The Silent Patient"}
                if model == "model-b"
                else {"title": None}
            )
            return LLMResponse(
                tool_calls=[ToolCall(name=tool, arguments=json.dumps(data))],
                usage={"total_tokens": 5},
            )
        # verifier: judge from the data echoed in the user message
        user = messages[-1]["content"]
        verdict = "supported" if '"title": "The Silent Patient"' in user else "not_found"
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    name="report_verification",
                    arguments=json.dumps({"fields": [{"name": "title", "verdict": verdict}]}),
                )
            ]
        )


def _patch(monkeypatch, provider=None):
    provider = provider or QualityFake()
    monkeypatch.setattr("app.llm.registry.load_config", _config)
    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: provider)
    return provider


async def _llm_models() -> list[str]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(Run).where(Run.kind == "llm"))).scalars().all()
    return [r.model for r in rows]


# ---------- override plumbing ----------

async def test_use_models_routes_agent_to_candidate(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    msg = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    await get_router().complete("extractor", messages=msg)
    with use_models({"extractor": "b"}):
        await get_router().complete("extractor", messages=msg)
        # explicit kwarg still beats the contextvar
        await get_router().complete("extractor", messages=msg, model="a")
    assert fake.models_seen == ["model-a", "model-b", "model-a"]


# ---------- experiments ----------

async def test_experiment_ranks_candidates_and_records(temp_db, monkeypatch):
    _patch(monkeypatch)
    out = await experiments.run_experiment("extractor", ["a", "b"], [TASK])
    assert out["winner"] == "b"
    assert out["promoted"] is False  # not requested
    means = {r["candidate"]: r["mean_score"] for r in out["results"]}
    assert means["b"] > means["a"]
    assert means["b"] == 1.0

    async with session_scope() as s:
        rows = (
            (await s.execute(select(Benchmark).where(Benchmark.metric == "experiment_score")))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert {r.meta["candidate"] for r in rows} == {"a", "b"}
    assert all(r.meta["experiment"] == out["experiment"] for r in rows)


async def test_failing_candidate_scores_zero(temp_db, monkeypatch):
    _patch(monkeypatch, QualityFake(fail_model="model-a"))
    out = await experiments.run_experiment("extractor", ["a", "b"], [TASK])
    means = {r["candidate"]: r["mean_score"] for r in out["results"]}
    assert means["a"] == 0.0
    assert out["winner"] == "b"


async def test_auto_promote_on_decisive_win(temp_db, monkeypatch):
    _patch(monkeypatch)
    out = await experiments.run_experiment("extractor", ["a", "b"], [TASK], promote=True)
    assert out["promoted"] is True
    promos = await experiments.list_promotions()
    assert promos[0]["agent"] == "extractor"
    assert promos[0]["model"] == "b"


async def test_no_promotion_on_tie(temp_db, monkeypatch):
    _patch(monkeypatch)  # b and b2 both resolve to model-b -> identical scores
    out = await experiments.run_experiment("extractor", ["b", "b2"], [TASK], promote=True)
    assert out["promoted"] is False
    assert await experiments.list_promotions() == []


# ---------- promotion API ----------

async def test_promote_list_demote_api(client):
    resp = await client.post(
        "/v1/experiments/promote", json={"agent": "extractor", "model": "b"}
    )
    assert resp.status_code == 200

    promos = (await client.get("/v1/experiments/promotions")).json()["promotions"]
    assert promos[0]["model"] == "b"

    assert (await client.delete("/v1/experiments/promotions/extractor")).status_code == 200
    assert (await client.delete("/v1/experiments/promotions/extractor")).status_code == 404


# ---------- router integration ----------

async def test_promotion_applied_when_flag_on(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    await experiments.promote_model("extractor", "b")
    monkeypatch.setattr(get_settings(), "apply_model_promotions", True)
    await get_router().complete(
        "extractor", messages=[{"role": "user", "content": "x"}]
    )
    assert fake.models_seen == ["model-b"]
    assert (await _llm_models()) == ["model-b"]


async def test_promotion_ignored_by_default(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    await experiments.promote_model("extractor", "b")
    await get_router().complete(
        "extractor", messages=[{"role": "user", "content": "x"}]
    )
    assert fake.models_seen == ["model-a"]  # flag off -> config wins


async def test_unconfigured_promotion_falls_back(temp_db, monkeypatch):
    fake = _patch(monkeypatch)
    await experiments.promote_model("extractor", "ghost")
    monkeypatch.setattr(get_settings(), "apply_model_promotions", True)
    await get_router().complete(
        "extractor", messages=[{"role": "user", "content": "x"}]
    )
    assert fake.models_seen == ["model-a"]  # graceful fallback, no crash


# ---------- route end-to-end ----------

async def test_experiment_route(client, monkeypatch):
    _patch(monkeypatch)
    resp = await client.post(
        "/v1/experiments/run",
        json={
            "agent": "extractor",
            "candidates": ["a", "b"],
            "tasks": [{"content": CONTENT, "schema": SCHEMA}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["winner"] == "b"
    assert len(body["results"]) == 2
