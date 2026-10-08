from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..core.pipeline import index_config_hash
from ..engine import okf, sync
from ..ingest import documents as docs_svc
from ..ingest import jobs
from ..ingest.documents import OKF, DocumentError

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


async def _usage_counts(project_id: str) -> dict[str, int]:
    """OKF usage_count: chunk appearances per document in the retrieval results of recent runs."""
    # ponytail: counts only the latest 2000 chat runs so GET /documents stays cheap; keep a
    # per-document counter updated in runs.finish_run if lifetime counts are ever needed.
    rows = await db.fetch_all(
        "SELECT json_extract(j.value, '$.document_id') AS doc, COUNT(*) AS n"
        " FROM (SELECT result FROM runs WHERE project_id=? AND kind='chat' AND result IS NOT NULL"
        "       ORDER BY created_at DESC LIMIT 2000) r, json_each(r.result, '$.retrieved') j"
        " GROUP BY doc", (project_id,))
    return {r["doc"]: r["n"] for r in rows}


_DOC_SQL = ("SELECT d.*, o.metadata AS okf, o.last_modified FROM documents d"
            " LEFT JOIN document_okf o ON o.document_id = d.id")


def _doc_out(d: dict[str, Any], build_rows: dict[str, dict[str, Any]], usage: dict[str, int]) -> dict[str, Any]:
    b = build_rows.get(d["id"])
    return {
        "id": d["id"], "filename": d["filename"], "source_url": d["source_url"], "mime": d["mime"],
        "size_bytes": d["size_bytes"], "status": d["status"], "error": d["error"],
        "parse_quality": db.loads(d["parse_quality"]), "created_at": d["created_at"],
        "last_modified": d["last_modified"],
        "okf": {**db.loads(d["okf"], {}), "usage_count": usage.get(d["id"], 0)},
        # Per active index: None = not in the active index yet.
        "chunks": b["chunk_count"] if b else None,
        "index_error": b["error"] if b else None,
    }


@router.get("")
async def list_documents(project_id: str) -> list[dict[str, Any]]:
    await _require_project(project_id)
    return await _documents(project_id)


async def _documents(project_id: str, doc_id: str | None = None) -> list[dict[str, Any]]:
    rows = await db.fetch_all(f"{_DOC_SQL} WHERE d.project_id=? AND (? IS NULL OR d.id=?)"
                              " ORDER BY d.created_at DESC, d.id", (project_id, doc_id, doc_id))
    cfg = await _active_cfg(project_id)
    build_rows: dict[str, dict[str, Any]] = {}
    if cfg:
        b = await db.fetch_one("SELECT id FROM index_builds WHERE project_id=? AND index_config_hash=?",
                               (project_id, index_config_hash(cfg)))
        if b:
            for r in await db.fetch_all("SELECT * FROM build_documents WHERE build_id=?", (b["id"],)):
                build_rows[r["document_id"]] = r
    usage = await _usage_counts(project_id)
    return [_doc_out(d, build_rows, usage) for d in rows]


@router.post("", status_code=201)
async def upload_documents(project_id: str, files: list[UploadFile] = File(...),
                           last_modified: list[int] | None = Form(None),
                           build: bool = Query(True)) -> dict[str, Any]:
    """`last_modified`: optional, one per file in the same order (browser File.lastModified, epoch ms)."""
    await _require_project(project_id)
    created, duplicates, errors = [], [], []
    for i, f in enumerate(files):
        try:
            data = await f.read()
            modified = docs_svc.iso_from_ms(last_modified[i]) if last_modified and i < len(last_modified) else None
            doc, new = await docs_svc.create_document(project_id, f.filename or "document", data,
                                                      last_modified=modified)
            (created if new else duplicates).append({"id": doc["id"], "filename": doc["filename"]})
        except DocumentError as e:
            errors.append({"filename": f.filename, "error": str(e)})
    job_id = None
    cfg = await _active_cfg(project_id)
    if build and created and cfg:
        job_id = sync.start_sync(project_id, cfg).id
    return {"created": created, "duplicates": duplicates, "errors": errors, "job_id": job_id}


@router.post("/okf", status_code=201)
async def import_okf_bundle(project_id: str, file: UploadFile = File(...),
                            build: bool = Query(True)) -> dict[str, Any]:
    """Import an OKF bundle (a zip of Markdown with YAML front matter): one document per Markdown file,
    its OKF fields read from the front matter; anything else is skipped with a reason (FR-3.18)."""
    await _require_project(project_id)
    try:
        out = await okf.import_bundle(project_id, await file.read())
    except DocumentError as e:
        raise HTTPException(422, str(e)) from e
    cfg = await _active_cfg(project_id)
    out["job_id"] = sync.start_sync(project_id, cfg).id if build and out["created"] and cfg else None
    return out


@router.get("/okf-export")
async def export_okf_bundle(project_id: str) -> Response:
    """The corpus as an OKF bundle: text + provenance, trust tier, lifecycle, usage, health findings (FR-3.20)."""
    await _require_project(project_id)
    data = await okf.export_bundle(project_id, await _usage_counts(project_id))
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="knowledge-base-okf.zip"'})


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


@router.patch("/{doc_id}/metadata")
async def update_metadata(project_id: str, doc_id: str, body: OKF) -> dict[str, Any]:
    """Replace a document's OKF fields. Not index config: never triggers a rebuild."""
    if not await db.fetch_one("SELECT id FROM documents WHERE id=? AND project_id=?", (doc_id, project_id)):
        raise HTTPException(404, "document not found")
    async with db.tx() as c:
        await c.execute("INSERT INTO document_okf (document_id, metadata) VALUES (?, ?)"
                        " ON CONFLICT(document_id) DO UPDATE SET metadata=excluded.metadata",
                        (doc_id, db.dumps(body.model_dump(mode="json", exclude_none=True))))
    return (await _documents(project_id, doc_id))[0]


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
