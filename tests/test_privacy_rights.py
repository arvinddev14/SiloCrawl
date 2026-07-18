"""Data-subject rights surface (must keep the privacy policy literally true):
crawl-job list/export/delete and telemetry export/purge."""
from datetime import datetime, timedelta, timezone

from app.db import audit_store, crawl_store, telemetry_store
from app.db.base import session_scope
from app.db.models import TelemetryEvent
from app.models.schemas import CrawlJob, CrawlStatus
from app.services import jobstore


async def _event(session, kind: str, message: str, age_hours: float) -> None:
    session.add(
        TelemetryEvent(
            kind=kind,
            message=message,
            created_at=datetime.now(timezone.utc) - timedelta(hours=age_hours),
        )
    )


# ---------- crawl store ----------

async def test_list_and_delete_crawl_jobs(temp_db):
    await jobstore.create("a", url="https://a.example")
    await jobstore.create("b", url="https://b.example")

    jobs = await crawl_store.list_crawl_jobs()
    assert {j["id"] for j in jobs} == {"a", "b"}
    assert all("payload" not in j for j in jobs)  # index only, no page content

    assert await crawl_store.delete_crawl_job("a") is True
    assert await crawl_store.delete_crawl_job("a") is False  # already gone
    remaining = {j["id"] for j in await crawl_store.list_crawl_jobs()}
    assert remaining == {"b"}


# ---------- telemetry store ----------

async def test_export_and_purge_by_window(temp_db):
    async with session_scope() as s:
        await _event(s, "scrape", "old", age_hours=48)
        await _event(s, "scrape", "recent", age_hours=1)

    exported = await telemetry_store.export_events()
    assert {e["message"] for e in exported} == {"old", "recent"}

    # purge only events older than 24h -> the 48h one goes, the 1h one stays
    removed = await telemetry_store.purge_events(older_than_hours=24)
    assert removed == 1
    assert {e["message"] for e in await telemetry_store.export_events()} == {"recent"}

    # purge all
    assert await telemetry_store.purge_events() == 1
    assert await telemetry_store.export_events() == []


# ---------- endpoints ----------

async def test_crawl_list_and_delete_endpoints(client):
    await jobstore.save(
        CrawlJob(id="job1", status=CrawlStatus.completed, total=1, completed=1),
        url="https://example.com",
    )

    listed = await client.get("/v1/crawl")
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["id"] == "job1"

    # export a single job with its captured content
    full = await client.get("/v1/crawl/job1")
    assert full.status_code == 200 and full.json()["id"] == "job1"

    assert (await client.delete("/v1/crawl/job1")).status_code == 200
    assert (await client.delete("/v1/crawl/job1")).status_code == 404
    assert (await client.get("/v1/crawl/job1")).status_code == 404


async def test_telemetry_export_and_purge_endpoints(client):
    async with session_scope() as s:
        await _event(s, "scrape", "e1", age_hours=1)
        await _event(s, "map", "e2", age_hours=1)

    export = await client.get("/v1/telemetry")
    assert export.status_code == 200
    assert export.json()["count"] == 2

    purge = await client.delete("/v1/telemetry")
    assert purge.status_code == 200
    assert purge.json()["deleted"] == 2
    assert (await client.get("/v1/telemetry")).json()["count"] == 0


# ---------- deletion audit log ----------

async def test_deletions_are_logged_atomically(temp_db):
    await jobstore.create("j", url="https://example.com")
    async with session_scope() as s:
        await _event(s, "scrape", "e", age_hours=1)

    await crawl_store.delete_crawl_job("j", actor="key-abc")
    await telemetry_store.purge_events(older_than_hours=0, actor="key-abc")

    log = await audit_store.list_deletions()
    kinds = {d["target_type"]: d for d in log}
    assert set(kinds) == {"crawl_job", "telemetry"}
    assert kinds["crawl_job"]["target_id"] == "j"
    assert kinds["crawl_job"]["count"] == 1
    assert kinds["telemetry"]["count"] == 1
    assert all(d["actor"] == "key-abc" for d in log)


async def test_failed_delete_is_not_logged(temp_db):
    assert await crawl_store.delete_crawl_job("nope") is False
    assert await telemetry_store.purge_events() == 0  # nothing to purge
    assert await audit_store.list_deletions() == []  # no phantom log entries


async def test_audit_endpoint_reports_deletions(client):
    await jobstore.save(
        CrawlJob(id="k", status=CrawlStatus.completed), url="https://example.com"
    )
    await client.delete("/v1/crawl/k")

    resp = await client.get("/v1/audit/deletions")
    assert resp.status_code == 200
    entries = resp.json()["deletions"]
    assert entries[0]["target_type"] == "crawl_job"
    assert entries[0]["target_id"] == "k"
    assert entries[0]["created_at"] is not None
