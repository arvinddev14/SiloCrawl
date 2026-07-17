import json

from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.llm.registry import Registry
from app.models.schemas import ExtractRequest
from app.services import extractor


def test_agents_resolve_to_gptoss():
    reg = Registry()
    for agent in ("extractor", "planner", "verifier", "repair", "ocr", "coder"):
        spec = reg.resolve(agent)
        assert spec.provider == "openai_compat"
        assert spec.model == "openai/gpt-oss-120b"


def test_unknown_agent_falls_back_to_default():
    reg = Registry()
    spec = reg.resolve("does-not-exist")
    assert spec.model == "openai/gpt-oss-120b"


def test_provider_instances_are_cached():
    reg = Registry()
    spec = reg.resolve("extractor")
    assert reg.provider_for(spec) is reg.provider_for(spec)


async def test_extractor_uses_router(monkeypatch):
    """The extractor must go through the router and never touch a provider SDK."""
    captured = {}

    async def fake_complete(agent, *, messages, tools=None, tool_choice=None, max_tokens=None, **kw):
        captured["agent"] = agent
        captured["tools"] = tools
        return LLMResponse(
            text=None,
            tool_calls=[ToolCall(name="emit_extracted_data", arguments=json.dumps({"title": "Hi"}))],
        )

    monkeypatch.setattr(get_router(), "complete", fake_complete)

    result = await extractor.extract(
        ExtractRequest(content="some page text", json_schema={"type": "object"})
    )

    assert result.data == {"title": "Hi"}
    assert captured["agent"] == "extractor"
    assert captured["tools"][0]["function"]["name"] == "emit_extracted_data"
