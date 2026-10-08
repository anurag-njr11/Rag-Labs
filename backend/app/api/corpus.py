from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .. import db
from ..engine import health, monitor
from ..ingest import jobs
from .eval import _version

router = APIRouter(prefix="/api/projects/{project_id}/health", tags=["health"])


class ReportIn(BaseModel):
    version_id: str | None = None
    # Real user questions, e.g. from support tickets; combined with Playground/API history.
    questions: list[str] = Field(default_factory=list, max_length=500)
    # Staleness: flag documents whose last-modified date is older than this many days.
    stale_days: int = Field(health.STALE_DAYS, ge=1, le=36500)
    # "api": only production traffic from the API, not Playground testing (FR-3.22)
    sources: Literal["all", "api"] = "all"


def _out(r: dict[str, Any], full: bool = True) -> dict[str, Any]:
    out = {k: r[k] for k in ("id", "project_id", "version_id", "build_id", "status", "error", "created_at")}
    out["trigger"], out["sources"] = r.get("trigger") or "manual", r.get("sources") or "all"
    out["version"] = r.get("version")
    result = db.loads(r["result"], None)
    if full:
        out["result"] = result
    else:  # list view: headline numbers only
        out["summary"] = result and {
            **result["coverage"]["summary"], "topics": len(result["coverage"]["topics"]),
            "contradictions": len(result["contradictions"]), "duplicates": len(result["duplicates"]),
            "unused_documents": result["usage"]["unused_documents"],
            "stale_documents": len((result.get("staleness") or {}).get("documents", [])),
            "trend": result.get("trend")}
    return out


async def _report(project_id: str, report_id: str) -> dict[str, Any]:
    r = await db.fetch_one("SELECT r.*, v.version FROM corpus_reports r LEFT JOIN pipeline_versions v"
                           " ON v.id = r.version_id WHERE r.id=? AND r.project_id=?", (report_id, project_id))
    if r is None:
        raise HTTPException(404, "report not found")
    return r


@router.post("/reports", status_code=201)
async def create_report(project_id: str, body: ReportIn) -> dict[str, Any]:
    v = await _version(project_id, body.version_id)
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    if not docs or docs["n"] == 0:
        raise HTTPException(409, "Add documents before checking corpus health.")
    pasted = [q.strip()[:500] for q in body.questions if q.strip()]
    report_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO corpus_reports (id, project_id, version_id, questions, trigger, sources, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", (report_id, project_id, v["id"], db.dumps(pasted), "manual",
                                                    body.sources, db.now_iso()))
    job = jobs.start("health", project_id, lambda job: health.run_report(job, report_id, project_id, v, pasted,
                                                                           body.stale_days, sources=body.sources))
    return {"report": _out(await _report(project_id, report_id)), "job_id": job.id}


@router.get("/monitor")
async def get_monitor(project_id: str) -> dict[str, Any]:
    """Production loop: the monitor's settings and real questions since the last report (FR-3.22)."""
    await _version(project_id, None)
    return {"settings": (await monitor.settings(project_id)).model_dump(),
            "since_last_report": await monitor.since_last_report(project_id)}


@router.put("/monitor")
async def put_monitor(project_id: str, body: monitor.MonitorSettings) -> dict[str, Any]:
    await _version(project_id, None)
    await monitor.save(project_id, body)
    job_id = await monitor.maybe_trigger(project_id)  # already past the threshold? start now
    return {**await get_monitor(project_id), "job_id": job_id}


@router.get("/reports")
async def list_reports(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT r.*, v.version FROM corpus_reports r LEFT JOIN pipeline_versions v"
                              " ON v.id = r.version_id WHERE r.project_id=? ORDER BY r.created_at DESC, r.rowid DESC",
                              (project_id,))
    return [_out(r, full=False) for r in rows]


@router.get("/reports/{report_id}")
async def get_report(project_id: str, report_id: str) -> dict[str, Any]:
    return _out(await _report(project_id, report_id))


@router.get("/reports/{report_id}/report.md")
async def report_markdown(project_id: str, report_id: str) -> Response:
    r = _out(await _report(project_id, report_id))
    if r["status"] != "ready":
        raise HTTPException(409, "This report isn't ready yet.")
    p = await db.fetch_one("SELECT name FROM projects WHERE id=?", (project_id,))
    return Response(health.to_markdown(r, p["name"] if p else project_id), media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="corpus-health-{report_id[:8]}.md"'})
