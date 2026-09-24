from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..engine import evaluate, sync
from ..ingest import jobs

router = APIRouter(prefix="/api/projects/{project_id}/eval", tags=["eval"])


class EvalSetIn(BaseModel):
    size: int = Field(30, ge=5, le=100)
    version_id: str | None = None


class EvalRunIn(BaseModel):
    version_id: str | None = None


async def _version(project_id: str, version_id: str | None) -> dict[str, Any]:
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")
    if version_id:
        v = await db.fetch_one("SELECT * FROM pipeline_versions WHERE id=? AND project_id=?",
                               (version_id, project_id))
    else:
        v = await sync.active_version(project_id)
    if v is None:
        raise HTTPException(404, "version not found")
    return v


async def _set(project_id: str, set_id: str) -> dict[str, Any]:
    s = await db.fetch_one("SELECT * FROM eval_sets WHERE id=? AND project_id=?", (set_id, project_id))
    if s is None:
        raise HTTPException(404, "eval set not found")
    return s


def _set_out(s: dict[str, Any]) -> dict[str, Any]:
    return {**s, "stats": db.loads(s["stats"], {})}


def _run_out(r: dict[str, Any], full: bool = False) -> dict[str, Any]:
    out = {k: r[k] for k in ("id", "eval_set_id", "version_id", "build_id", "status", "error", "created_at")}
    out["version"] = r.get("version")
    out["metrics"] = db.loads(r["metrics"], None)
    if full:
        out["results"] = db.loads(r["results"], [])
    return out


@router.post("/sets", status_code=201)
async def create_set(project_id: str, body: EvalSetIn) -> dict[str, Any]:
    v = await _version(project_id, body.version_id)
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    if not docs or docs["n"] == 0:
        raise HTTPException(409, "Add documents before generating an eval set.")
    set_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_sets (id, project_id, version_id, size_requested, created_at)"
                        " VALUES (?,?,?,?,?)", (set_id, project_id, v["id"], body.size, db.now_iso()))
    job = jobs.start("evalset", project_id,
                     lambda job: evaluate.generate_set(job, set_id, project_id, v, body.size))
    return {"eval_set": _set_out(await _set(project_id, set_id)), "job_id": job.id}


@router.get("/sets")
async def list_sets(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM eval_sets WHERE project_id=? ORDER BY created_at DESC, rowid DESC",
                              (project_id,))
    return [_set_out(r) for r in rows]


@router.get("/sets/{set_id}")
async def get_set(project_id: str, set_id: str) -> dict[str, Any]:
    s = _set_out(await _set(project_id, set_id))
    items = await db.fetch_all(
        "SELECT i.*, d.filename AS document FROM eval_items i LEFT JOIN documents d ON d.id = i.document_id"
        " WHERE i.eval_set_id=? ORDER BY i.ordinal", (set_id,))
    s["items"] = [{**i, "valid": bool(i["valid"])} for i in items]
    return s


@router.post("/sets/{set_id}/runs", status_code=201)
async def create_run(project_id: str, set_id: str, body: EvalRunIn) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    run_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES (?,?,?,?,?)", (run_id, set_id, project_id, v["id"], db.now_iso()))
    job = jobs.start("eval", project_id, lambda job: evaluate.run_eval(job, run_id, project_id, set_id, v))
    return {"run": await _get_run(project_id, run_id), "job_id": job.id}


async def _get_run(project_id: str, run_id: str, full: bool = False) -> dict[str, Any]:
    r = await db.fetch_one(
        "SELECT r.*, v.version FROM eval_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
        " WHERE r.id=? AND r.project_id=?", (run_id, project_id))
    if r is None:
        raise HTTPException(404, "eval run not found")
    return _run_out(r, full)


@router.get("/runs")
async def list_runs(project_id: str, set_id: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT r.*, v.version FROM eval_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
           " WHERE r.project_id=?")
    params: tuple = (project_id,)
    if set_id:
        sql += " AND r.eval_set_id=?"
        params += (set_id,)
    rows = await db.fetch_all(sql + " ORDER BY r.created_at, r.rowid", params)
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(project_id: str, run_id: str) -> dict[str, Any]:
    return await _get_run(project_id, run_id, full=True)
