"""The Model Router — the single entry point every AI agent uses.

Agent -> Router -> Provider. Agents pass a role name ("extractor", "verifier",
...); the router resolves role -> model -> provider from config. No agent
imports a provider SDK directly, and switching an agent to a different
open-source model is a config change with no code impact.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core import telemetry
from app.core.config import get_settings
from app.llm import overrides
from app.llm.base import LLMResponse, ModelSpec
from app.llm.registry import Registry

logger = logging.getLogger("silocrawl")

# Cache of agent -> promoted alias, invalidated whenever a promotion changes.
_promotion_cache: dict[str, str] | None = None


async def _promoted_model(agent: str) -> str | None:
    """Best-effort promotion lookup (INC-B14). DB trouble = no promotion."""
    global _promotion_cache
    if _promotion_cache is None:
        try:
            from sqlalchemy import select

            from app.db.base import session_scope
            from app.db.models import ModelPromotion

            async with session_scope() as session:
                rows = (await session.execute(select(ModelPromotion))).scalars().all()
            _promotion_cache = {r.agent: r.model for r in rows}
        except Exception:  # noqa: BLE001 - never block an LLM call on this
            logger.warning("promotion_lookup_failed", exc_info=True)
            return None  # don't cache the failure
    return _promotion_cache.get(agent)


def invalidate_promotions() -> None:
    global _promotion_cache
    _promotion_cache = None


class ModelRouter:
    def __init__(self) -> None:
        self._registry = Registry()

    async def _resolve_spec(self, agent: str, model: str | None) -> ModelSpec:
        """Resolution order: explicit kwarg > contextvar override (experiments)
        > promoted winner (flag-gated, graceful) > config."""
        explicit = model if model is not None else overrides.current_override(agent)
        if explicit is not None:
            return self._registry.resolve(agent, explicit)  # unknown alias raises
        if get_settings().apply_model_promotions:
            promoted = await _promoted_model(agent)
            if promoted is not None:
                try:
                    return self._registry.resolve(agent, promoted)
                except KeyError:
                    logger.warning(
                        "promoted_model_not_configured",
                        extra={"agent": agent, "model": promoted},
                    )
        return self._registry.resolve(agent)

    async def complete(
        self,
        agent: str,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        max_tokens: int | None = None,
        model: str | None = None,  # per-call alias override (Planner/B14)
        **kw: Any,
    ) -> LLMResponse:
        spec = await self._resolve_spec(agent, model)
        provider = self._registry.provider_for(spec)
        # Every agent's LLM usage is observable centrally, by design.
        async with telemetry.track("llm") as run:
            run.agent = agent
            run.model = spec.model
            response = await provider.complete(
                model=spec.model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens or spec.max_tokens,
                **kw,
            )
            if response.usage:
                run.tokens = response.usage.get("total_tokens")
            return response


@lru_cache
def get_router() -> ModelRouter:
    return ModelRouter()
