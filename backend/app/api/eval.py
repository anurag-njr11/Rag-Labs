from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .. import db
from ..core.pipeline import diff_pipelines
from ..engine import evaluate, sweep, sync
from ..ingest import jobs

router = APIRouter(prefix="/api/projects/{project_id}/eval", tags=["eval"])


class EvalSetIn(BaseModel):
    size: int = Field(30, ge=5, le=100)
    version_id: str | None = None


class ItemIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    gold_answer: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=4000)
    document_id: str


class ItemPatch(BaseModel):
    question: str | None = Field(None, min_length=3, max_length=1000)
    gold_answer: str | None = Field(None, min_length=1, max_length=2000)
    evidence: str | None = Field(None, min_length=1, max_length=4000)
    valid: bool | None = None  # restore a rejected item / drop a kept one


class CsvIn(BaseModel):
    csv: str = Field(max_length=2_000_000)


CSV_COLUMNS = ["question", "gold_answer", "evidence", "document", "valid", "reject_reason"]


class EvalRunIn(BaseModel):
    version_id: str | None = None
    answers: bool = False  # also generate + LLM-grade each answer


class AxisIn(BaseModel):
    path: str = Field(pattern=r"^[a-z_]+\.[a-z_]+$")
    values: list[Any] = Field(min_length=1, max_length=12)


class SweepIn(BaseModel):
    set_id: str
    version_id: str | None = None
    axes: list[AxisIn] = Field(min_length=1, max_length=4)
    # Successive halving: answer-grade the top 25% of cells by retrieval (at most 5) after scoring all.
    auto_optimize: bool = False


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


# --- hand edits (FR-2.4) ----------------------------------------------------------
# Runs keep their per-item results; a run scored before an edit used the old questions.

async def _item(set_id: str, item_id: str) -> dict[str, Any]:
    it = await db.fetch_one("SELECT * FROM eval_items WHERE id=? AND eval_set_id=?", (item_id, set_id))
    if it is None:
        raise HTTPException(404, "item not found")
    return it


async def _add_item(s: dict[str, Any], body: ItemIn) -> str:
    doc = await db.fetch_one("SELECT id FROM documents WHERE id=? AND project_id=?", (body.document_id, s["project_id"]))
    if doc is None:
        raise HTTPException(422, "Unknown document.")
    reason = await evaluate.check_evidence(s["build_id"], body.document_id, body.evidence)
    if reason:
        raise HTTPException(422, reason)
    item_id = db.new_id()
    async with db.tx() as c:
        row = await (await c.execute("SELECT COALESCE(MAX(ordinal), -1) + 1 FROM eval_items WHERE eval_set_id=?",
                                     (s["id"],))).fetchone()
        await c.execute(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id, valid) VALUES (?,?,?,?,?,?,?,'',1)",
            (item_id, s["id"], row[0], body.question.strip(), body.gold_answer.strip(), body.evidence.strip(),
             body.document_id))
    return item_id


@router.post("/sets/{set_id}/items", status_code=201)
async def add_item(project_id: str, set_id: str, body: ItemIn) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    return {**await _item(set_id, await _add_item(s, body)), "valid": True}


@router.patch("/sets/{set_id}/items/{item_id}")
async def update_item(project_id: str, set_id: str, item_id: str, body: ItemPatch) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    it = await _item(set_id, item_id)
    changes = body.model_dump(exclude_none=True)
    if "evidence" in changes:
        reason = await evaluate.check_evidence(s["build_id"], it["document_id"], changes["evidence"])
        if reason:
            raise HTTPException(422, reason)
    if changes.get("valid") is True and "evidence" not in changes:
        reason = await evaluate.check_evidence(s["build_id"], it["document_id"], it["evidence"])
        if reason:
            raise HTTPException(422, f"Can't restore it: {reason}")
    if "valid" in changes:
        changes["valid"] = int(changes["valid"])
        if changes["valid"]:
            changes["reject_reason"] = None
        else:
            changes.setdefault("reject_reason", "removed by hand")
    if changes:
        cols = ", ".join(f"{k}=?" for k in changes)
        async with db.tx() as c:
            await c.execute(f"UPDATE eval_items SET {cols} WHERE id=?", (*changes.values(), item_id))
    it = await _item(set_id, item_id)
    return {**it, "valid": bool(it["valid"])}


@router.delete("/sets/{set_id}/items/{item_id}", status_code=204)
async def delete_item(project_id: str, set_id: str, item_id: str) -> None:
    await _set(project_id, set_id)
    await _item(set_id, item_id)
    async with db.tx() as c:
        await c.execute("DELETE FROM eval_items WHERE id=?", (item_id,))


@router.get("/sets/{set_id}/export.csv")
async def export_csv(project_id: str, set_id: str) -> Response:
    await _set(project_id, set_id)
    items = await db.fetch_all(
        "SELECT i.*, d.filename AS document FROM eval_items i LEFT JOIN documents d ON d.id = i.document_id"
        " WHERE i.eval_set_id=? ORDER BY i.ordinal", (set_id,))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for i in items:
        w.writerow({**i, "valid": "yes" if i["valid"] else "no", "reject_reason": i["reject_reason"] or ""})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="eval-set-{set_id[:8]}.csv"'})


@router.post("/sets/{set_id}/import")
async def import_csv(project_id: str, set_id: str, body: CsvIn) -> dict[str, Any]:
    """Add rows from a CSV with columns question, gold_answer (or answer), evidence, document
    (the filename). Rows marked valid=no are skipped. Each row is checked like a hand-added item."""
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    reader = csv.DictReader(io.StringIO(body.csv.lstrip("\ufeff")))
    cols = {c.strip().lower() for c in reader.fieldnames or []}
    if not {"question", "evidence", "document"} <= cols or not {"gold_answer", "answer"} & cols:
        raise HTTPException(422, "The CSV needs columns: question, gold_answer (or answer), evidence, document.")
    docs = {d["filename"]: d["id"] for d in await db.fetch_all(
        "SELECT id, filename FROM documents WHERE project_id=?", (project_id,))}
    added, errors = 0, []
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if row.get("valid", "yes").lower() in ("no", "false", "0"):
            continue
        doc_id = docs.get(row.get("document", ""))
        if doc_id is None:
            errors.append({"row": n, "message": f"No document named {row.get('document')!r} in this project."})
            continue
        try:
            body_in = ItemIn(question=row.get("question", ""), gold_answer=row.get("gold_answer") or row.get("answer", ""),
                             evidence=row.get("evidence", ""), document_id=doc_id)
            await _add_item(s, body_in)
            added += 1
        except HTTPException as e:
            errors.append({"row": n, "message": str(e.detail)})
        except ValueError as e:  # pydantic validation
            errors.append({"row": n, "message": str(e).splitlines()[-1].strip() or "Invalid row."})
    return {"added": added, "errors": errors[:50], "error_count": len(errors)}


@router.post("/sets/{set_id}/runs", status_code=201)
async def create_run(project_id: str, set_id: str, body: EvalRunIn) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    run_id, job_id = await start_run(project_id, set_id, v, body.answers)
    return {"run": await _get_run(project_id, run_id), "job_id": job_id}


async def start_run(project_id: str, set_id: str, v: dict[str, Any], answers: bool = False) -> tuple[str, str]:
    run_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES (?,?,?,?,?)", (run_id, set_id, project_id, v["id"], db.now_iso()))
    job = jobs.start("eval", project_id,
                     lambda job: evaluate.run_eval(job, run_id, project_id, set_id, v, answers))
    return run_id, job.id


async def regression_check(project_id: str, v: dict[str, Any]) -> str | None:
    """Regression guard: score a newly saved version on the newest ready eval set.
    Returns the eval job id, or None when the project has no ready set."""
    s = await db.fetch_one("SELECT id FROM eval_sets WHERE project_id=? AND status='ready'"
                           " ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id,))
    if s is None:
        return None
    return (await start_run(project_id, s["id"], v))[1]


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


@router.get("/runs/{run_id}/fixes")
async def run_fixes(project_id: str, run_id: str) -> list[dict[str, Any]]:
    """One-click fixes for the run's miss diagnoses: each a full config to save as a new version."""
    run = await _get_run(project_id, run_id, full=True)
    v = await _version(project_id, run["version_id"])
    cfg = sync.version_config(v)
    out = []
    for diagnosis in evaluate.DIAGNOSES:
        new = evaluate.suggest_fix(cfg, diagnosis, run["results"])
        if new is not None:
            out.append({"diagnosis": diagnosis, "config": new, "changes": diff_pipelines(cfg, new),
                        "base_version": run["version"]})
    return out


# --- sweeps -------------------------------------------------------------------

def _sweep_out(s: dict[str, Any]) -> dict[str, Any]:
    cells = db.loads(s["cells"], [])
    counts: dict[str, int] = {}
    for c in cells:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {**s, "axes": db.loads(s["axes"], []), "cells": cells, "counts": counts}


async def _sweep(project_id: str, sweep_id: str) -> dict[str, Any]:
    s = await db.fetch_one("SELECT s.*, v.version AS base_version FROM sweeps s LEFT JOIN pipeline_versions v"
                           " ON v.id = s.base_version_id WHERE s.id=? AND s.project_id=?", (sweep_id, project_id))
    if s is None:
        raise HTTPException(404, "sweep not found")
    return _sweep_out(s)


@router.get("/sweep-axes")
async def sweep_axes(project_id: str) -> dict[str, Any]:
    return {"axes": sweep.AXES, "max_cells": sweep.MAX_CELLS}


@router.post("/sweeps", status_code=201)
async def create_sweep(project_id: str, body: SweepIn) -> dict[str, Any]:
    s = await _set(project_id, body.set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    axes = [a.model_dump() for a in body.axes]
    try:
        cells = sweep.expand_grid(sync.version_config(v), axes)
    except sweep.SweepError as e:
        raise HTTPException(422, str(e)) from e
    sweep_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", (sweep_id, project_id, s["id"], v["id"], db.dumps(axes),
                                                    db.dumps(cells), db.now_iso()))
    job = jobs.start("sweep", project_id, lambda job: sweep.run_sweep(job, sweep_id, body.auto_optimize))
    return {"sweep": await _sweep(project_id, sweep_id), "job_id": job.id}


@router.get("/sweeps")
async def list_sweeps(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT s.*, v.version AS base_version FROM sweeps s LEFT JOIN pipeline_versions v"
                              " ON v.id = s.base_version_id WHERE s.project_id=?"
                              " ORDER BY s.created_at DESC, s.rowid DESC", (project_id,))
    return [_sweep_out(r) for r in rows]


@router.get("/sweeps/{sweep_id}")
async def get_sweep(project_id: str, sweep_id: str) -> dict[str, Any]:
    return await _sweep(project_id, sweep_id)


@router.post("/sweeps/{sweep_id}/cancel")
async def cancel_sweep(project_id: str, sweep_id: str) -> dict[str, Any]:
    await _sweep(project_id, sweep_id)
    async with db.tx() as c:
        await c.execute("UPDATE sweeps SET status='cancelled' WHERE id=? AND status='running'", (sweep_id,))
    return await _sweep(project_id, sweep_id)
