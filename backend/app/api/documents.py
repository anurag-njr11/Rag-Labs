from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..core.pipeline import index_config_hash
from ..engine import sync
from ..ingest import documents as docs_svc
from ..ingest import jobs
from ..ingest.documents import DocumentError

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["documents"])


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    sitemap: bool = False
    max_pages: int = Field(50, ge=1, le=1000)
    build: bool = True  # False: fetch only; index later (e.g. after the wizard's Configure step)


async def _require_project(project_id: str) -> None:
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")


async def _active_cfg(project_id: str) -> dict[str, Any] | None:
    v = await sync.active_version(project_id)
    return db.loads(v["config"]) if v else None


def _doc_out(d: dict[str, Any], build_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    b = build_rows.get(d["id"])
    return {
        "id": d["id"], "filename": d["filename"], "source_url": d["source_url"], "mime": d["mime"],
        "size_bytes": d["size_bytes"], "status": d["status"], "error": d["error"],
        "parse_quality": db.loads(d["parse_quality"]), "created_at": d["created_at"],
        # Per active index: None = not in the active index yet.
        "chunks": b["chunk_count"] if b else None,
        "index_error": b["error"] if b else None,
    }


@router.get("")
async def list_documents(project_id: str) -> list[dict[str, Any]]:
    await _require_project(project_id)
    rows = await db.fetch_all("SELECT * FROM documents WHERE project_id=? ORDER BY created_at DESC, id",
                              (project_id,))
    cfg = await _active_cfg(project_id)
    build_rows: dict[str, dict[str, Any]] = {}
    if cfg:
        b = await db.fetch_one("SELECT id FROM index_builds WHERE project_id=? AND index_config_hash=?",
                               (project_id, index_config_hash(cfg)))
        if b:
            for r in await db.fetch_all("SELECT * FROM build_documents WHERE build_id=?", (b["id"],)):
                build_rows[r["document_id"]] = r
    return [_doc_out(d, build_rows) for d in rows]


@router.post("", status_code=201)
async def upload_documents(project_id: str, files: list[UploadFile] = File(...),
                           build: bool = Query(True)) -> dict[str, Any]:
    await _require_project(project_id)
    created, duplicates, errors = [], [], []
    for f in files:
        try:
            data = await f.read()
            doc, new = await docs_svc.create_document(project_id, f.filename or "document", data)
            (created if new else duplicates).append({"id": doc["id"], "filename": doc["filename"]})
        except DocumentError as e:
            errors.append({"filename": f.filename, "error": str(e)})
    job_id = None
    cfg = await _active_cfg(project_id)
    if build and created and cfg:
        job_id = sync.start_sync(project_id, cfg).id
    return {"created": created, "duplicates": duplicates, "errors": errors, "job_id": job_id}


@router.post("/url", status_code=202)
async def add_url(project_id: str, body: UrlIn) -> dict[str, Any]:
    await _require_project(project_id)
    cfg = await _active_cfg(project_id)
    if cfg is None:
        raise HTTPException(409, "project has no configuration")

    async def fetch(job):
        if body.sitemap:
            return await docs_svc.crawl_sitemap(project_id, body.url, body.max_pages, job)
        job.progress("fetch", 0, 1, f"Fetching {body.url}")
        doc, new = await docs_svc.create_from_url(project_id, body.url)
        job.progress("fetch", 1, 1, f"Fetched {doc['filename']}")
        return {"pages": 1, "created": int(new), "duplicates": int(not new), "failed": 0}

    if not body.build:
        async def fetch_only(job):
            return {"fetch": await fetch(job)}

        return {"job_id": jobs.start("fetch", project_id, fetch_only).id}
    job = sync.start_sync(project_id, cfg, before=fetch)
    return {"job_id": job.id}


@router.delete("/{doc_id}", status_code=204)
async def delete_document(project_id: str, doc_id: str) -> None:
    if not await docs_svc.delete_document(project_id, doc_id):
        raise HTTPException(404, "document not found")


@router.post("/{doc_id}/reindex")
async def reindex_document(project_id: str, doc_id: str) -> dict[str, Any]:
    """Re-run the active index for one document (e.g. after a failure)."""
    doc = await db.fetch_one("SELECT id FROM documents WHERE id=? AND project_id=?", (doc_id, project_id))
    if doc is None:
        raise HTTPException(404, "document not found")
    cfg = await _active_cfg(project_id)
    if cfg is None:
        raise HTTPException(409, "project has no configuration")
    b = await db.fetch_one("SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?",
                           (project_id, index_config_hash(cfg)))
    if b:
        from ..ingest import builder

        await builder._remove_documents(b, [doc_id])
        async with db.tx() as c:
            await c.execute("UPDATE index_builds SET status='pending' WHERE id=?", (b["id"],))
    async with db.tx() as c:
        await c.execute("UPDATE documents SET status='uploaded', error=NULL WHERE id=?", (doc_id,))
    return {"job_id": sync.start_sync(project_id, cfg).id}


@router.get("/{doc_id}/chunks")
async def document_chunks(project_id: str, doc_id: str, limit: int = Query(200, le=2000)) -> dict[str, Any]:
    cfg = await _active_cfg(project_id)
    if cfg is None:
        raise HTTPException(409, "project has no configuration")
    b = await db.fetch_one("SELECT id FROM index_builds WHERE project_id=? AND index_config_hash=?",
                           (project_id, index_config_hash(cfg)))
    if b is None:
        return {"chunks": [], "total": 0}
    rows = await db.fetch_all(
        "SELECT id, ordinal, text, token_count, is_table, page_start, page_end, heading_path FROM chunks"
        " WHERE build_id=? AND document_id=? ORDER BY ordinal LIMIT ?", (b["id"], doc_id, limit))
    total = await db.fetch_one("SELECT COUNT(*) AS n FROM chunks WHERE build_id=? AND document_id=?",
                               (b["id"], doc_id))
    for r in rows:
        r["is_table"] = bool(r["is_table"])
    return {"chunks": rows, "total": total["n"] if total else 0}
