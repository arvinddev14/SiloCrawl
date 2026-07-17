"""Load the agent->model map and the model registry.

Resolution precedence:
  1. ``models.yaml`` (path from ``Settings.models_config_path``) if it exists.
  2. Otherwise a default built from ``Settings`` (every agent -> gpt-oss-120b).

``${VAR}`` placeholders in the YAML are expanded from the process environment,
falling back to the matching ``Settings`` field (pydantic loads ``.env`` into
``Settings``, not into ``os.environ``).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.llm.base import ModelSpec

_VAR = re.compile(r"\$\{([^}]+)\}")

# Roles the rest of SiloLoop will call the router with.
_AGENT_ROLES = ("default", "planner", "extractor", "verifier", "repair", "ocr", "coder")


def _expand(value: Any, ctx: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _VAR.sub(lambda m: ctx.get(m.group(1), ""), value)
    return value


def _interpolation_ctx() -> dict[str, str]:
    """Values available for ${VAR} expansion. Process env wins over .env/Settings."""
    s = get_settings()
    ctx: dict[str, str] = {
        "HF_API_KEY": s.hf_api_key,
        "HF_ENDPOINT_URL": s.hf_endpoint_url,
        "EXTRACT_MODEL": s.extract_model,
    }
    ctx.update(os.environ)
    return ctx


def _default_config() -> tuple[dict[str, str], dict[str, ModelSpec]]:
    s = get_settings()
    alias = "gpt-oss-120b"
    agents = {role: alias for role in _AGENT_ROLES}
    models = {
        alias: ModelSpec(
            alias=alias,
            provider="openai_compat",
            model=s.extract_model,
            endpoint=s.hf_endpoint_url,
            api_key=s.hf_api_key,
            max_tokens=s.extract_max_tokens,
        )
    }
    return agents, models


def load_config() -> tuple[dict[str, str], dict[str, ModelSpec]]:
    path = Path(get_settings().models_config_path)
    if not path.is_file():
        return _default_config()

    import yaml

    ctx = _interpolation_ctx()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    agents = {str(k): str(v) for k, v in (raw.get("agents") or {}).items()}
    models: dict[str, ModelSpec] = {}
    for alias, cfg in (raw.get("models") or {}).items():
        cfg = cfg or {}
        reserved = {"provider", "model", "endpoint", "api_key", "max_tokens"}
        models[str(alias)] = ModelSpec(
            alias=str(alias),
            provider=str(cfg.get("provider", "openai_compat")),
            model=str(_expand(cfg.get("model", ""), ctx)),
            endpoint=str(_expand(cfg.get("endpoint", ""), ctx)),
            api_key=str(_expand(cfg.get("api_key", ""), ctx)),
            max_tokens=int(cfg.get("max_tokens", 4096)),
            params={k: v for k, v in cfg.items() if k not in reserved},
        )

    # A malformed/empty file should never brick the engine.
    if not agents or not models:
        return _default_config()
    return agents, models
