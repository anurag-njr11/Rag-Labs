"""Production query loop (FR-3.22)."""

import asyncio

import httpx

from app import db
from app.engine import health, monitor
from app.ingest import builder, jobs
from app.nodes import generate as G
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


async def _runs(n, source, status="ok", q="question"):
    async with db.tx() as c:
        await c.executemany(
            "INSERT INTO runs (id, project_id, kind, question, status, source, created_at) VALUES (?, 'p', 'chat', ?, ?, ?, ?)",
            [(db.new_id(), f"{q} {i}", status, source, db.now_iso()) for i in range(n)])


def test_trend():
    prev = {"coverage": {"summary": {"covered_rate": 0.5},
                         "outcomes": {"a": "gap", "b": "covered", "c": "retrieval_miss"}}}
    cur = {"a": "covered", "b": "gap", "c": "covered", "d": "gap", "e": "covered"}
    t = monitor.trend(prev, cur, 0.6)
    assert t == {"previous_covered_rate": 0.5, "covered_rate_change": 0.1, "resolved": 2, "regressed": 1,
                 "new_gaps": 1, "new_questions": 2}
    assert monitor.trend(None, cur, 0.6) is None


async def test_source_is_recorded_and_counted(project, monkeypatch):  # noqa: F811
    from app.main import app

    async def stream(self, messages, usage):
        yield "Three times [1]."

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        await c.post("/api/projects/p/chat", json={"question": "retries?", "stream": False},
                     headers={"X-RAGLabs-Client": "playground"})
        await c.post("/api/projects/p/chat", json={"question": "retries again?", "stream": False})
    rows = await db.fetch_all("SELECT question, source FROM runs ORDER BY created_at")
    assert [r["source"] for r in rows] == ["playground", "api"]
    assert await monitor.since_last_report("p") == {"last_report_at": None, "api": 1, "playground": 1, "all": 2}
    assert [q["question"] for q in await health.real_questions("p", [], "api")] == ["retries again?"]


async def test_trigger_needs_enabled_threshold_and_no_running_report(project, monkeypatch):  # noqa: F811
    started = []

    async def fake_report(job, report_id, project_id, version, extra, stale_days, sources="all"):
        started.append(sources)
        async with db.tx() as c:
            await c.execute("UPDATE corpus_reports SET status='ready', result='{}' WHERE id=?", (report_id,))
        return {}

    monkeypatch.setattr(health, "run_report", fake_report)
    cfg = _cfg("numpy")
    v = await _version(cfg)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    await _runs(6, "playground")
    await _runs(4, "api")
    assert await monitor.maybe_trigger("p") is None  # off
    await monitor.save("p", monitor.MonitorSettings(enabled=True, every_n=5, sources="api"))
    assert await monitor.maybe_trigger("p") is None  # only 4 API questions
    await _runs(1, "api", status="error")
    assert await monitor.maybe_trigger("p") is None  # failed runs don't count
    await _runs(1, "api")
    job_id = await monitor.maybe_trigger("p")
    assert job_id
    await jobs.get(job_id)._task
    r = await db.fetch_one("SELECT trigger, sources FROM corpus_reports")
    assert (r["trigger"], r["sources"]) == ("auto", "api") and started == ["api"]
    assert (await monitor.since_last_report("p"))["all"] == 0  # counting restarts after a report
    await _runs(5, "api")
    blocker = jobs.start("health", "p", lambda job: asyncio.sleep(0.2))
    assert await monitor.maybe_trigger("p") is None  # a report is already running
    await blocker._task


async def test_monitor_api(project):  # noqa: F811
    from app.main import app

    v = await _version(_cfg("numpy"))
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        got = (await c.get("/api/projects/p/health/monitor")).json()
        assert got["settings"]["enabled"] is False and got["since_last_report"]["all"] == 0
        put = await c.put("/api/projects/p/health/monitor", json={"enabled": True, "every_n": 20, "sources": "all"})
        assert put.status_code == 200 and put.json()["settings"]["every_n"] == 20 and put.json()["job_id"] is None
        assert (await c.put("/api/projects/p/health/monitor", json={"every_n": 1})).status_code == 422
