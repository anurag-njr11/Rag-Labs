from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..core.pipeline import (
    PipelineError, diff_pipelines, index_config_hash, recommended_pipeline, validate_pipeline, with_defaults,
)
from ..engine import stores, sync
from ..ingest import builder

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1000)
    config: dict[str, Any] | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=1000)


class VersionIn(BaseModel):
    config: dict[str, Any]
    note: str = Field("", max_length=300)
    activate: bool = True
    build: bool = True


def _validate(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_pipeline(cfg)
    except PipelineError as e:
        raise HTTPException(422, {"message": "Invalid configuration", "errors": e.errors}) from e


async def _project(project_id: str) -> dict[str, Any]:
    p = await db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if p is None:
        raise HTTPException(404, "project not found")
    return p


async def _version(project_id: str, version_id: str) -> dict[str, Any]:
    v = await db.fetch_one("SELECT * FROM pipeline_versions WHERE id=? AND project_id=?", (version_id, project_id))
    if v is None:
        raise HTTPException(404, "version not found")
    return v


async def build_status(project_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Status of the index for a configuration, as the UI shows it."""
    b = await db.fetch_one("SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?",
                           (project_id, index_config_hash(cfg)))
    running = sync._running.get((project_id, index_config_hash(cfg)))
    job_id = running.id if running and running.status == "running" else None
    if b is None:
        return {"status": "not_built", "chunk_count": 0, "store": cfg["vector_store"]["type"], "job_id": job_id}
    synced = await builder.build_is_synced(b)
    status = b["status"]
    if status == "ready" and not synced:
        status = "stale"
    if job_id:
        status = "building"
    return {"id": b["id"], "status": status, "chunk_count": b["chunk_count"], "store": b["store_type"],
            "dim": b["dim"], "error": b["error"], "stats": db.loads(b["stats"], {}),
            "finished_at": b["finished_at"], "job_id": job_id}


def _version_out(v: dict[str, Any], active_id: str | None) -> dict[str, Any]:
    return {"id": v["id"], "version": v["version"], "note": v["note"], "created_at": v["created_at"],
            "index_config_hash": index_config_hash(db.loads(v["config"], {})), "parent_id": v["parent_id"],
            "active": v["id"] == active_id, "config": db.loads(v["config"], {})}


async def _project_out(p: dict[str, Any]) -> dict[str, Any]:
    counts = await db.fetch_one(
        "SELECT (SELECT COUNT(*) FROM documents WHERE project_id=:p) AS documents,"
        " (SELECT COUNT(*) FROM pipeline_versions WHERE project_id=:p) AS versions", {"p": p["id"]})
    active = await sync.active_version(p["id"])
    out = {**p, **(counts or {}), "active_version": None, "index": None}
    if active:
        cfg = db.loads(active["config"], {})
        out["active_version"] = _version_out(active, p["active_version_id"])
        out["index"] = await build_status(p["id"], cfg)
        out["summary"] = {
            "vector_store": cfg["vector_store"]["type"],
            "embed_model": cfg["embed"].get("model") or cfg["embed"]["type"],
            "generate": cfg["generate"]["type"],
            "model": cfg["generate"].get("model") or "",
        }
    return out


async def _insert_version(project_id: str, cfg: dict[str, Any], note: str, parent_id: str | None,
                          activate: bool) -> dict[str, Any]:
    vid = db.new_id()
    async with db.tx() as c:
        row = await (await c.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM pipeline_versions WHERE project_id=?", (project_id,)
        )).fetchone()
        await c.execute(
            "INSERT INTO pipeline_versions (id, project_id, version, config, index_config_hash, parent_id, note,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, project_id, row[0], db.dumps(cfg), index_config_hash(cfg), parent_id, note, db.now_iso()),
        )
        if activate:
            await c.execute("UPDATE projects SET active_version_id=? WHERE id=?", (vid, project_id))
    return await db.fetch_one("SELECT * FROM pipeline_versions WHERE id=?", (vid,))  # type: ignore[return-value]


async def _maybe_build(project_id: str, cfg: dict[str, Any]) -> str | None:
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    if not docs or docs["n"] == 0:
        return None
    b = await db.fetch_one("SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?",
                           (project_id, index_config_hash(cfg)))
    if b and await builder.build_is_synced(b):
        return None
    return sync.start_sync(project_id, cfg).id


# --- projects ---------------------------------------------------------------

@router.get("")
async def list_projects() -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM projects ORDER BY created_at DESC")
    return [await _project_out(p) for p in rows]


@router.post("", status_code=201)
async def create_project(body: ProjectIn) -> dict[str, Any]:
    cfg = _validate(body.config) if body.config else recommended_pipeline()
    pid = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO projects (id, name, description, created_at) VALUES (?, ?, ?, ?)",
                        (pid, body.name.strip(), body.description.strip(), db.now_iso()))
    await _insert_version(pid, cfg, "Initial configuration", None, activate=True)
    return await _project_out(await _project(pid))


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    return await _project_out(await _project(project_id))


@router.patch("/{project_id}")
async def update_project(project_id: str, body: ProjectPatch) -> dict[str, Any]:
    await _project(project_id)
    fields = {k: v.strip() for k, v in body.model_dump(exclude_none=True).items()}
    if fields:
        async with db.tx() as c:
            await c.execute(f"UPDATE projects SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                            (*fields.values(), project_id))
    return await _project_out(await _project(project_id))


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str) -> None:
    await _project(project_id)
    docs = await db.fetch_all("SELECT raw_path FROM documents WHERE project_id=?", (project_id,))
    for b in await db.fetch_all("SELECT id FROM index_builds WHERE project_id=?", (project_id,)):
        await stores.close_store(b["id"])
    async with db.tx() as c:
        # FTS and lookup tables have no foreign keys.
        builds = [r[0] for r in await (await c.execute(
            "SELECT id FROM index_builds WHERE project_id=?", (project_id,))).fetchall()]
        for bid in builds:
            await c.execute("DELETE FROM chunks_fts WHERE build_id=?", (bid,))
            await c.execute("DELETE FROM lookup_index WHERE build_id=?", (bid,))
        await c.execute("DELETE FROM projects WHERE id=?", (project_id,))
    for d in docs:
        await asyncio.to_thread(shutil.rmtree, Path(d["raw_path"]).parent, True)
    await asyncio.to_thread(shutil.rmtree, get_settings().stores_dir / project_id, True)


# --- versions ---------------------------------------------------------------

@router.get("/{project_id}/versions")
async def list_versions(project_id: str) -> list[dict[str, Any]]:
    p = await _project(project_id)
    rows = await db.fetch_all("SELECT * FROM pipeline_versions WHERE project_id=? ORDER BY version DESC",
                              (project_id,))
    out = []
    for v in rows:
        item = _version_out(v, p["active_version_id"])
        item["index"] = await build_status(project_id, item["config"])
        out.append(item)
    return out


@router.get("/{project_id}/versions/diff")
async def diff_versions(project_id: str, a: str, b: str) -> dict[str, Any]:
    va, vb = await _version(project_id, a), await _version(project_id, b)
    return {"a": va["version"], "b": vb["version"],
            "changes": diff_pipelines(db.loads(va["config"]), db.loads(vb["config"]))}


@router.get("/{project_id}/versions/{version_id}")
async def get_version(project_id: str, version_id: str) -> dict[str, Any]:
    p = await _project(project_id)
    v = _version_out(await _version(project_id, version_id), p["active_version_id"])
    v["index"] = await build_status(project_id, v["config"])
    parent = await db.fetch_one("SELECT config, version FROM pipeline_versions WHERE id=?", (v["parent_id"],)) \
        if v["parent_id"] else None
    v["changes_from_parent"] = diff_pipelines(db.loads(parent["config"]), v["config"]) if parent else []
    v["parent_version"] = parent["version"] if parent else None
    return v


@router.post("/{project_id}/versions", status_code=201)
async def create_version(project_id: str, body: VersionIn) -> dict[str, Any]:
    p = await _project(project_id)
    cfg = _validate(body.config)
    active = await sync.active_version(project_id)
    if active and with_defaults(db.loads(active["config"])) == cfg:
        return {"version": _version_out(active, p["active_version_id"]), "job_id": None, "unchanged": True}
    v = await _insert_version(project_id, cfg, body.note.strip(), active["id"] if active else None, body.activate)
    job_id = await _maybe_build(project_id, cfg) if body.build else None
    p = await _project(project_id)
    return {"version": _version_out(v, p["active_version_id"]), "job_id": job_id, "unchanged": False}


@router.post("/{project_id}/versions/{version_id}/activate")
async def activate_version(project_id: str, version_id: str) -> dict[str, Any]:
    v = await _version(project_id, version_id)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id=?", (version_id, project_id))
    return {"version": _version_out(v, version_id), "job_id": await _maybe_build(project_id, db.loads(v["config"]))}


@router.post("/{project_id}/versions/{version_id}/rollback", status_code=201)
async def rollback_version(project_id: str, version_id: str) -> dict[str, Any]:
    v = await _version(project_id, version_id)
    active = await sync.active_version(project_id)
    cfg = _validate(db.loads(v["config"]))
    nv = await _insert_version(project_id, cfg, f"Rolled back to v{v['version']}",
                               active["id"] if active else None, activate=True)
    return {"version": _version_out(nv, nv["id"]), "job_id": await _maybe_build(project_id, cfg)}


@router.post("/{project_id}/versions/{version_id}/build")
async def build_version(project_id: str, version_id: str) -> dict[str, Any]:
    v = await _version(project_id, version_id)
    cfg = db.loads(v["config"])
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    if not docs or docs["n"] == 0:
        raise HTTPException(409, "Add documents before building the index.")
    return {"job_id": sync.start_sync(project_id, cfg).id}


@router.post("/{project_id}/estimate")
async def estimate(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    await _project(project_id)
    cfg = _validate(body.get("config", {}))
    active = await sync.active_version(project_id)
    changes = diff_pipelines(db.loads(active["config"]), cfg) if active else []
    return {
        "changes": changes,
        "rebuild_needed": any(c["effect"] == "rebuild" for c in changes),
        "estimate": await builder.estimate(project_id, cfg),
        "index_config_hash": index_config_hash(cfg),
    }


# --- builds -----------------------------------------------------------------

@router.get("/{project_id}/builds")
async def list_builds(project_id: str) -> list[dict[str, Any]]:
    await _project(project_id)
    rows = await db.fetch_all(
        "SELECT id, index_config_hash, config, store_type, status, dim, chunk_count, error, stats,"
        " started_at, finished_at FROM index_builds WHERE project_id=? ORDER BY started_at DESC", (project_id,))
    for r in rows:
        r["config"] = db.loads(r["config"], {})
        r["stats"] = db.loads(r["stats"], {})
    return rows
