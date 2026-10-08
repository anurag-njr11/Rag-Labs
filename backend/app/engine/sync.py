"""Starting index syncs as background jobs, one per (project, index config)."""

from __future__ import annotations

import hashlib
from typing import Any

from .. import db
from ..core.pipeline import index_config_hash
from ..ingest import builder, jobs
from ..ingest.jobs import Job

_running: dict[tuple[str, str], Job] = {}


async def corpus_sha(project_id: str) -> str:
    """Fingerprint of the project's documents: sha256 of their sorted content hashes (FR-2.5)."""
    rows = await db.fetch_all("SELECT content_sha FROM documents WHERE project_id=?", (project_id,))
    return hashlib.sha256("\n".join(sorted(r["content_sha"] for r in rows)).encode()).hexdigest()


def version_config(version: dict[str, Any]) -> dict[str, Any]:
    return db.loads(version["config"], {})


def start_sync(project_id: str, cfg: dict[str, Any], *, before: Any = None) -> Job:
    """Start (or join) the sync job for this config's build. `before` is an
    optional coroutine function run first inside the job (e.g. fetching URLs)."""
    key = (project_id, index_config_hash(cfg))
    running = _running.get(key)
    if running is not None and running.status == "running" and before is None:
        return running

    async def run(job: Job) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if before is not None:
            result["fetch"] = await before(job)
        build = await builder.sync_build(project_id, cfg, job)
        result["build"] = {"id": build["id"], "status": build["status"], "chunk_count": build["chunk_count"],
                           "stats": db.loads(build["stats"], {})}
        return result

    job = jobs.start("sync", project_id, run)
    _running[key] = job
    return job


async def active_version(project_id: str) -> dict[str, Any] | None:
    return await db.fetch_one(
        "SELECT v.* FROM pipeline_versions v JOIN projects p ON p.active_version_id = v.id WHERE p.id=?",
        (project_id,),
    )
