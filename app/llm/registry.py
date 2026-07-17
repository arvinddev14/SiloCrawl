"""Resolve an agent role to a ModelSpec, and cache provider instances."""
from __future__ import annotations

from app.llm.base import LLMProvider, ModelSpec
from app.llm.config import load_config
from app.llm.providers import PROVIDERS


class Registry:
    def __init__(self) -> None:
        # cache providers by connection identity so SDK key/endpoint overrides
        # (which change these values) naturally produce a fresh client.
        self._providers: dict[tuple[str, str, str], LLMProvider] = {}

    def resolve(self, agent: str, model: str | None = None) -> ModelSpec:
        agents, models = load_config()
        if model is not None:
            # Explicit per-call override (Planner / cross-model evaluation, B14).
            if model not in models:
                raise KeyError(f"Model override '{model}' is not defined under models:.")
            return models[model]
        alias = agents.get(agent) or agents.get("default")
        if alias is None:
            raise KeyError(f"No model configured for agent '{agent}' and no default set.")
        if alias not in models:
            raise KeyError(
                f"Agent '{agent}' maps to model '{alias}', which is not defined under models:."
            )
        return models[alias]

    def provider_for(self, spec: ModelSpec) -> LLMProvider:
        key = (spec.provider, spec.endpoint, spec.api_key)
        provider = self._providers.get(key)
        if provider is None:
            try:
                cls = PROVIDERS[spec.provider]
            except KeyError as e:
                raise KeyError(
                    f"Unknown provider '{spec.provider}'. Known: {sorted(PROVIDERS)}"
                ) from e
            provider = cls(endpoint=spec.endpoint, api_key=spec.api_key)
            self._providers[key] = provider
        return provider
