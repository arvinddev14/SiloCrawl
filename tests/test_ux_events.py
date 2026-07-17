from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import TelemetryEvent
from app.services import evaluator


async def _ux_rows():
    async with session_scope() as s:
        return (
            (await s.execute(select(TelemetryEvent).where(TelemetryEvent.kind == "ux")))
            .scalars()
            .all()
        )


async def _seed(name: str, value: float | None = None, n: int = 1):
    async with session_scope() as s:
        for _ in range(n):
            meta = {"value": value} if value is not None else None
            s.add(TelemetryEvent(kind="ux", message=name, meta=meta))


# ---------- POST /v1/events ----------

async def test_post_events_persists(client):
    resp = await client.post(
        "/v1/events",
        json={
            "events": [
                {"name": "playground.request", "meta": {"endpoint": "scrape"}},
                {"name": "playground.wait", "value": 1234.0},
            ]
        },
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 2}

    rows = await _ux_rows()
    assert len(rows) == 2
    wait = next(r for r in rows if r.message == "playground.wait")
    assert wait.meta["value"] == 1234.0
    req = next(r for r in rows if r.message == "playground.request")
    assert req.meta["endpoint"] == "scrape"


async def test_post_events_batch_cap(client):
    events = [{"name": f"e{i}"} for i in range(51)]
    resp = await client.post("/v1/events", json={"events": events})
    assert resp.status_code == 422  # over the 50-event cap


async def test_post_events_malformed(client):
    assert (await client.post("/v1/events", json={"events": []})).status_code == 422
    assert (await client.post("/v1/events", json={"nope": 1})).status_code == 422


async def test_post_events_persist_failure_still_202(client, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.api.routes.session_scope", boom)
    resp = await client.post("/v1/events", json={"events": [{"name": "x"}]})
    assert resp.status_code == 202  # fire-and-forget survives persistence loss


# ---------- ux_report ----------

async def test_ux_report_aggregates_and_recommends(temp_db):
    await _seed("playground.request", n=4)
    await _seed("playground.error", n=1)
    await _seed("playground.abandon", n=2)
    await _seed("playground.wait", value=6000)
    await _seed("playground.wait", value=8000)

    report = await evaluator.ux_report(hours=0)
    assert report["events"]["playground.request"] == 4
    assert report["avg_wait_ms"] == 7000.0
    assert report["error_rate"] == 0.25
    assert report["abandon_rate"] == 0.5
    # all three rules fire: wait > 5s, error rate > 20%, abandon rate > 25%
    assert len(report["recommendations"]) == 3


async def test_ux_report_quiet_when_healthy(temp_db):
    await _seed("playground.request", n=4)
    await _seed("playground.wait", value=800)
    report = await evaluator.ux_report(hours=0)
    assert report["recommendations"] == ["No UX issues detected in this window."]


# ---------- GET /v1/ux ----------

async def test_ux_route(client):
    await _seed("playground.request", n=2)
    resp = await client.get("/v1/ux", params={"hours": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"]["playground.request"] == 2
    assert "recommendations" in body


async def test_ux_route_empty_db(client):
    body = (await client.get("/v1/ux", params={"hours": 0})).json()
    assert body["events"] == {}
    assert body["avg_wait_ms"] is None
    assert body["error_rate"] == 0.0
    assert body["recommendations"] == ["No UX issues detected in this window."]
