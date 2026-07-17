"""Autonomous optimization (INC-B14): cross-model A/B experiments + promotions.

Each candidate model alias runs the *real* loop pipeline (with verification, so
confidence is the quality signal) over the same tasks; per-run score is
``success x confidence``. Every score is written to the benchmarks table tagged
with the experiment id and candidate, so results are fully auditable. A winner
is only auto-promoted when the caller asked for it AND the win is decisive
(clears the margin and the floor) — never on noise.

Promotions are runtime state in ``model_promotions``, not edits to models.yaml:
the config file stays the declarative source of what models exist; a promotion
records which one currently wins for an agent — listable and revocable, and only
applied to live routing when ``apply_model_promotions`` is enabled.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import ModelPromotion
from app.llm import router as router_module
from app.llm.overrides import use_models
from app.loop import benchmark, orchestrator
from app.models.schemas import ExtractRequest

logger = logging.getLogger("silocrawl")

# Auto-promotion needs a decisive win: lead over the runner-up plus an absolute
# quality floor. Ties and marginal wins never change routing.
PROMOTION_MARGIN = 0.05
PROMOTION_FLOOR = 0.5


async def _run_task(
    agent: str, candidate: str, task: ExtractRequest, verify: bool
) -> dict[str, Any]:
    steps = orchestrator.extract_steps(verify=verify)
    started = time.monotonic()
    try:
        with use_models({agent: candidate}):
            # model_copy: the planner may mutate the request (generated schema);
            # candidates must not see each other's side effects.
            result = await orchestrator.run(task.model_copy(deep=True), steps=steps)
        confidence = result.confidence if result.confidence is not None else 1.0
        score = round(confidence, 4)  # success is 1 by reaching here
    except Exception as e:  # noqa: BLE001 - a failing candidate scores 0
        logger.warning(
            "experiment_task_failed",
            extra={"agent": agent, "candidate": candidate, "error": str(e)},
        )
        score = 0.0
    return {"score": score, "duration_ms": int((time.monotonic() - started) * 1000)}


async def run_experiment(
    agent: str,
    candidates: list[str],
    tasks: list[ExtractRequest],
    *,
    verify: bool = True,
    promote: bool = False,
) -> dict[str, Any]:
    experiment_id = uuid.uuid4().hex[:12]
    summaries: list[dict[str, Any]] = []

    for candidate in candidates:
        scores: list[float] = []
        durations: list[int] = []
        for index, task in enumerate(tasks):
            outcome = await _run_task(agent, candidate, task, verify)
            scores.append(outcome["score"])
            durations.append(outcome["duration_ms"])
            await benchmark.record(
                None,
                {"experiment_score": outcome["score"]},
                meta={
                    "experiment": experiment_id,
                    "agent": agent,
                    "candidate": candidate,
                    "task": index,
                },
            )
        summaries.append(
            {
                "candidate": candidate,
                "mean_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
                "scores": scores,
                "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            }
        )

    ranked = sorted(summaries, key=lambda s: s["mean_score"], reverse=True)
    winner = ranked[0] if ranked else None

    promoted = False
    if promote and winner is not None:
        runner_up = ranked[1]["mean_score"] if len(ranked) > 1 else 0.0
        lead = winner["mean_score"] - runner_up
        if winner["mean_score"] >= PROMOTION_FLOOR and lead >= PROMOTION_MARGIN:
            await promote_model(
                agent,
                winner["candidate"],
                score=winner["mean_score"],
                meta={"experiment": experiment_id},
            )
            promoted = True

    return {
        "experiment": experiment_id,
        "agent": agent,
        "results": ranked,
        "winner": winner["candidate"] if winner else None,
        "promoted": promoted,
    }


async def promote_model(
    agent: str,
    model: str,
    score: float | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record (or replace) the promoted model for an agent."""
    async with session_scope() as session:
        row = await session.get(ModelPromotion, agent)
        if row is None:
            session.add(ModelPromotion(agent=agent, model=model, score=score, meta=meta))
        else:
            row.model, row.score, row.meta = model, score, meta
    router_module.invalidate_promotions()
    return {"agent": agent, "model": model, "score": score}


async def demote(agent: str) -> bool:
    """Revoke an agent's promotion. False if there wasn't one."""
    async with session_scope() as session:
        row = await session.get(ModelPromotion, agent)
        if row is None:
            return False
        await session.delete(row)
    router_module.invalidate_promotions()
    return True


async def list_promotions() -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = (await session.execute(select(ModelPromotion))).scalars().all()
    return [
        {
            "agent": r.agent,
            "model": r.model,
            "score": r.score,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
