"""SiloLoop ORM tables.

Only ``crawl_jobs`` is wired end-to-end at INC-3; the rest are scaffolding that
their own increments populate (telemetry -> INC-5, domain_strategies -> INC-B2,
knowledge -> INC-B6, benchmarks -> INC-B10, prompt_versions -> INC-B7).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CrawlJobRecord(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON)  # full CrawlJob.model_dump()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)  # scrape|map|extract|crawl|...
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    agent: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DomainStrategy(Base):
    __tablename__ = "domain_strategies"

    domain: Mapped[str] = mapped_column(String, primary_key=True)
    strategy: Mapped[str] = mapped_column(String)  # static|headers|browser|proxy
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    entity_type: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    predicate: Mapped[str] = mapped_column(String, index=True)
    object_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[float] = mapped_column(Float)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ModelPromotion(Base):
    """A model alias promoted for an agent by an experiment or by hand (INC-B14).

    Runtime state, deliberately separate from models.yaml: config declares what
    models exist; promotions record which one currently wins for an agent. Only
    applied to routing when ``apply_model_promotions`` is enabled.
    """

    __tablename__ = "model_promotions"

    agent: Mapped[str] = mapped_column(String, primary_key=True)
    model: Mapped[str] = mapped_column(String)  # alias under models: in config
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class DeletionLog(Base):
    """Append-only audit trail of data-subject erasures.

    Records metadata only — target type, a non-personal reference id, how many
    rows went, who asked, and when — never the deleted content itself, so the
    log can be retained after a GDPR erasure without re-introducing the data.
    """

    __tablename__ = "deletion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String, index=True)  # crawl_job | telemetry
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)  # job id; null = bulk
    count: Mapped[int] = mapped_column(Integer, default=0)  # rows removed
    actor: Mapped[str | None] = mapped_column(String, nullable=True)  # hashed api-key id
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    template: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
