"""Index builds.

A build is identified by (project, index config hash) and is *synced* to the
project's current documents: new documents are parsed, chunked, embedded and
written to the store; removed ones are deleted. Versions that differ only in
instant-effect parameters share a build.

Stages run across all pending documents at once — parse, chunk, embed, store —
so progress is per stage and stores that rebuild on write (FAISS) do so once.
Every expensive stage is served from a content-addressed cache when possible.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

import numpy as np

from .. import db
from ..config import get_settings
from ..core.cache import ArtifactCache, stable_hash, sha256_text
from ..core.node import build_node
from ..core.pipeline import PipelineConfig, index_config_hash, rebuild_part
from ..engine import stores
from ..nodes.chunk import approx_tokens
from . import lookup
from .jobs import Job

_locks: dict[str, asyncio.Lock] = {}


def _lock(build_id: str) -> asyncio.Lock:
    return _locks.setdefault(build_id, asyncio.Lock())


def artifacts() -> ArtifactCache:
    return ArtifactCache(get_settings().cache_dir / "artifacts")


def chunk_id(build_id: str, doc_id: str, ordinal: int) -> str:
    # Deterministic, and 32 hex chars so every store (incl. Qdrant's UUIDs) accepts it.
    return hashlib.sha256(f"{build_id}:{doc_id}:{ordinal}".encode()).hexdigest()[:32]


def chunking_key(cfg: PipelineConfig) -> str:
    part = rebuild_part(cfg)
    return stable_hash({"parse": part["parse"], "chunk": part["chunk"]})[:16]


async def get_or_create_build(project_id: str, cfg: PipelineConfig) -> dict[str, Any]:
    h = index_config_hash(cfg)
    row = await db.fetch_one(
        "SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?", (project_id, h)
    )
    if row:
        return row
    build_id = db.new_id()
    async with db.tx() as c:
        await c.execute(
            "INSERT OR IGNORE INTO index_builds (id, project_id, index_config_hash, config, store_type, store_path)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (build_id, project_id, h, db.dumps(rebuild_part(cfg)), cfg["vector_store"]["type"],
             str(stores.store_path(project_id, build_id))),
        )
    return await db.fetch_one(
        "SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?", (project_id, h)
    )  # type: ignore[return-value]


async def build_is_synced(build: dict[str, Any]) -> bool:
    if build["status"] != "ready":
        return False
    row = await db.fetch_one(
        "SELECT"
        " (SELECT COUNT(*) FROM documents WHERE project_id=?) AS docs,"
        " (SELECT COUNT(*) FROM build_documents WHERE build_id=?) AS built",
        (build["project_id"], build["id"]),
    )
    return bool(row) and row["docs"] == row["built"]


async def _set_build(build_id: str, **fields: Any) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    async with db.tx() as c:
        await c.execute(f"UPDATE index_builds SET {cols} WHERE id=?", (*fields.values(), build_id))


async def _cached_vectors(shas: list[str], embed_key: str) -> dict[str, np.ndarray]:
    found: dict[str, np.ndarray] = {}
    for i in range(0, len(shas), 500):
        part = shas[i:i + 500]
        rows = await db.fetch_all(
            f"SELECT text_sha, dim, vector FROM vector_cache WHERE embed_key=? AND text_sha IN"
            f" ({','.join('?' * len(part))})",
            (embed_key, *part),
        )
        for r in rows:
            found[r["text_sha"]] = np.frombuffer(r["vector"], dtype=np.float32)
    return found


async def sync_build(project_id: str, cfg: PipelineConfig, job: Job | None = None) -> dict[str, Any]:
    """Bring the build for `cfg` up to date with the project's documents."""
    build = await get_or_create_build(project_id, cfg)
    progress = job.progress if job else (lambda *a, **k: None)
    log = job.log if job else (lambda *a, **k: None)

    async with _lock(build["id"]):
        build = await db.fetch_one("SELECT * FROM index_builds WHERE id=?", (build["id"],))
        docs = await db.fetch_all(
            "SELECT * FROM documents WHERE project_id=? ORDER BY created_at, id", (project_id,)
        )
        built = {r["document_id"] for r in await db.fetch_all(
            "SELECT document_id FROM build_documents WHERE build_id=?", (build["id"],))}
        to_add = [d for d in docs if d["id"] not in built]
        to_remove = sorted(built - {d["id"] for d in docs})
        if not to_add and not to_remove and build["status"] == "ready":
            progress("ready", 1, 1, "Index is up to date")
            return build

        t0 = time.perf_counter()
        await _set_build(build["id"], status="building", error=None, started_at=db.now_iso())
        try:
            stats = await _index_documents(build, cfg, to_add, progress, log)
            if to_remove:
                await _remove_documents(build, to_remove)
            count = await db.fetch_one("SELECT COUNT(*) AS n FROM chunks WHERE build_id=?", (build["id"],))
            prev = db.loads(build["stats"], {})
            stats = {**prev, **stats, "seconds": round(time.perf_counter() - t0, 2),
                     "chunking_key": chunking_key(cfg), "embed_key": build_node("embed", cfg["embed"]).embed_key()}
            store_notes = []
            if build["id"] in stores._open:
                store_notes = stores._open[build["id"]].info().get("notes", [])
            stats["store_notes"] = store_notes
            await _set_build(build["id"], status="ready", chunk_count=count["n"] if count else 0,
                             stats=db.dumps(stats), finished_at=db.now_iso(),
                             dim=stats.get("dim") or build["dim"])
        except Exception as e:
            await _set_build(build["id"], status="failed", error=str(e), finished_at=db.now_iso())
            raise
        progress("ready", 1, 1, "Index ready")
        return await db.fetch_one("SELECT * FROM index_builds WHERE id=?", (build["id"],))  # type: ignore[return-value]


async def _index_documents(build: dict[str, Any], cfg: PipelineConfig, docs: list[dict[str, Any]],
                           progress: Any, log: Any) -> dict[str, Any]:
    stats: dict[str, Any] = {"docs_added": 0, "docs_failed": 0, "chunks_added": 0,
                             "parse_cache_hits": 0, "chunk_cache_hits": 0,
                             "vectors_cached": 0, "vectors_embedded": 0}
    if not docs:
        return stats
    cache = artifacts()
    parser = build_node("parse", cfg["parse"])
    chunker = build_node("chunk", cfg["chunk"])
    embedder = build_node("embed", cfg["embed"])
    part = rebuild_part(cfg)

    # 1. Parse + chunk -------------------------------------------------------
    prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for i, d in enumerate(docs):
        progress("parse", i, len(docs), f"Parsing {d['filename']}")
        parse_key = stable_hash({"doc": d["content_sha"], "parse": part["parse"]})
        chunk_key = stable_hash({"parsed": parse_key, "chunk": part["chunk"]})
        try:
            parsed = cache.get("parsed", parse_key)
            if parsed is None:
                kind = _kind(d)
                parsed = await asyncio.to_thread(parser.parse, Path(d["raw_path"]), kind)
                cache.put("parsed", parse_key, parsed)
            else:
                stats["parse_cache_hits"] += 1
            chunks = cache.get("chunks", chunk_key)
            if chunks is None:
                chunks = await asyncio.to_thread(chunker.chunk, parsed["pages"])
                cache.put("chunks", chunk_key, chunks)
            else:
                stats["chunk_cache_hits"] += 1
        except Exception as e:
            stats["docs_failed"] += 1
            log(f"{d['filename']}: {e}", "error")
            # Recorded per build, so a bad file is reported once rather than
            # retried on every sync. Re-indexing the document clears it.
            async with db.tx() as c:
                await c.execute("UPDATE documents SET status='failed', error=? WHERE id=?", (str(e), d["id"]))
                await c.execute(
                    "INSERT OR REPLACE INTO build_documents (build_id, document_id, chunk_count, error)"
                    " VALUES (?, ?, 0, ?)", (build["id"], d["id"], str(e)))
            continue
        async with db.tx() as c:
            await c.execute("UPDATE documents SET parse_quality=?, error=NULL WHERE id=?",
                            (db.dumps(parsed["quality"]), d["id"]))
        prepared.append((d, chunks))
    progress("parse", len(docs), len(docs), "Parsed")

    # 2. Embed (vector cache first) ------------------------------------------
    rows = [(d, n, c, sha256_text(c["text"])) for d, chunks in prepared for n, c in enumerate(chunks)]
    embed_key = embedder.embed_key()
    shas = list(dict.fromkeys(r[3] for r in rows))
    vectors = await _cached_vectors(shas, embed_key)
    stats["vectors_cached"] = len(vectors)
    missing = [s for s in shas if s not in vectors]
    if missing:
        text_by_sha = {r[3]: r[2]["text"] for r in rows}
        progress("embed", 0, len(missing), f"Embedding {len(missing)} chunks")

        def on_progress(done: int, total: int) -> None:
            progress("embed", done, total, f"Embedding {done}/{total}")

        mat = await embedder.embed_documents([text_by_sha[s] for s in missing], progress=on_progress)
        async with db.tx() as c:
            await c.executemany(
                "INSERT OR REPLACE INTO vector_cache (text_sha, embed_key, dim, vector) VALUES (?, ?, ?, ?)",
                [(s, embed_key, int(mat.shape[1]), mat[i].astype(np.float32).tobytes())
                 for i, s in enumerate(missing)],
            )
        for i, s in enumerate(missing):
            vectors[s] = mat[i]
        stats["vectors_embedded"] = len(missing)
    else:
        progress("embed", len(shas), len(shas), "All vectors served from cache")

    if not rows:
        await _record_documents(build, prepared, [])
        stats["docs_added"] = len(prepared)
        return stats

    # 3. Store ---------------------------------------------------------------
    dim = int(next(iter(vectors.values())).shape[0])
    if build["dim"] and int(build["dim"]) != dim:
        raise RuntimeError(f"embedding size changed ({build['dim']} → {dim}); this build can't mix them")
    build = {**build, "dim": dim}
    if not (await db.fetch_one("SELECT dim FROM index_builds WHERE id=?", (build["id"],)) or {}).get("dim"):
        await _set_build(build["id"], dim=dim)
    store = await stores.open_store(build)
    ids = [chunk_id(build["id"], d["id"], n) for d, n, _, _ in rows]
    progress("store", 0, len(ids), f"Writing {len(ids)} vectors to {cfg['vector_store']['type']}")
    matrix = np.vstack([vectors[r[3]] for r in rows]).astype(np.float32)
    await asyncio.to_thread(store.upsert, ids, [r[0]["id"] for r in rows], matrix)
    progress("store", len(ids), len(ids), "Vectors written")

    # 4. Chunk rows, keyword index, exact-match keys ---------------------------
    progress("keywords", 0, len(rows), "Building keyword and exact-match indexes")
    await _record_documents(build, prepared, [(cid, r) for cid, r in zip(ids, rows)])
    stats["docs_added"] = len(prepared)
    stats["chunks_added"] = len(rows)
    stats["dim"] = dim
    progress("keywords", len(rows), len(rows), "Indexes built")
    return stats


async def _record_documents(build: dict[str, Any], prepared: list, rows: list) -> None:
    chunk_rows, fts_rows, lookup_rows = [], [], []
    for cid, (d, n, c, sha) in rows:
        chunk_rows.append((cid, build["id"], d["id"], n, c["text"], sha, approx_tokens(c["text"]),
                           int(bool(c["is_table"])), c["page_start"], c["page_end"], c["heading_path"] or ""))
        fts_rows.append((c["text"], cid, build["id"], d["id"]))
        for kind, key in lookup.extract_keys(c["text"], c["heading_path"] or ""):
            lookup_rows.append((build["id"], cid, d["id"], kind, key))
    per_doc: dict[str, int] = {}
    for _, (d, *_rest) in rows:
        per_doc[d["id"]] = per_doc.get(d["id"], 0) + 1
    async with db.tx() as c:
        doc_ids = [d["id"] for d, _ in prepared]
        for doc_id in doc_ids:  # idempotent if a previous attempt half-finished
            await _delete_doc_rows(c, build["id"], doc_id)
        await c.executemany(
            "INSERT INTO chunks (id, build_id, document_id, ordinal, text, text_sha, token_count, is_table,"
            " page_start, page_end, heading_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", chunk_rows)
        await c.executemany(
            "INSERT INTO chunks_fts (text, chunk_id, build_id, document_id) VALUES (?, ?, ?, ?)", fts_rows)
        await c.executemany(
            "INSERT INTO lookup_index (build_id, chunk_id, document_id, kind, key) VALUES (?, ?, ?, ?, ?)",
            lookup_rows)
        await c.executemany(
            "INSERT OR REPLACE INTO build_documents (build_id, document_id, chunk_count) VALUES (?, ?, ?)",
            [(build["id"], doc_id, per_doc.get(doc_id, 0)) for doc_id in doc_ids])
        await c.executemany(
            "UPDATE documents SET status='indexed', error=NULL WHERE id=?", [(doc_id,) for doc_id in doc_ids])


async def _delete_doc_rows(c: Any, build_id: str, doc_id: str) -> None:
    await c.execute("DELETE FROM chunks_fts WHERE build_id=? AND document_id=?", (build_id, doc_id))
    await c.execute("DELETE FROM lookup_index WHERE build_id=? AND document_id=?", (build_id, doc_id))
    await c.execute("DELETE FROM chunks WHERE build_id=? AND document_id=?", (build_id, doc_id))
    await c.execute("DELETE FROM build_documents WHERE build_id=? AND document_id=?", (build_id, doc_id))


async def _remove_documents(build: dict[str, Any], doc_ids: list[str]) -> None:
    if build.get("dim"):
        store = await stores.open_store(build)
        await asyncio.to_thread(store.delete_documents, doc_ids)
    async with db.tx() as c:
        for doc_id in doc_ids:
            await _delete_doc_rows(c, build["id"], doc_id)


async def remove_document_everywhere(project_id: str, doc_id: str) -> None:
    """Remove a document from every build's store and indexes (before its row is deleted)."""
    for build in await db.fetch_all("SELECT * FROM index_builds WHERE project_id=?", (project_id,)):
        async with _lock(build["id"]):
            await _remove_documents(build, [doc_id])
            n = await db.fetch_one("SELECT COUNT(*) AS n FROM chunks WHERE build_id=?", (build["id"],))
            await _set_build(build["id"], chunk_count=n["n"] if n else 0)


def _kind(doc: dict[str, Any]) -> str:
    from .loaders import detect_kind

    kind = detect_kind(doc["raw_path"]) or detect_kind(doc["filename"])
    if kind is None:
        raise ValueError(f"unsupported file type: {doc['filename']}")
    return kind


async def estimate(project_id: str, cfg: PipelineConfig) -> dict[str, Any]:
    """What saving this configuration would cost, for the UI's rebuild estimate."""
    h = index_config_hash(cfg)
    build = await db.fetch_one(
        "SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?", (project_id, h))
    if build and await build_is_synced(build):
        return {"kind": "none", "message": "Index already built for these settings — switches instantly."}
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    ck, ek = chunking_key(cfg), build_node("embed", cfg["embed"]).embed_key()
    same_chunking = None
    for b in await db.fetch_all(
        "SELECT * FROM index_builds WHERE project_id=? AND status='ready'", (project_id,)
    ):
        s = db.loads(b["stats"], {})
        if s.get("chunking_key") == ck:
            if s.get("embed_key") == ek:
                return {"kind": "reinsert", "chunks": b["chunk_count"],
                        "message": f"Vectors cached — re-inserts {b['chunk_count']} chunks, no re-embedding."}
            same_chunking = b
    if same_chunking is not None:
        n = same_chunking["chunk_count"]
        return {"kind": "reembed", "chunks": n, "message": f"Re-embeds {n} chunks with the new model."}
    return {"kind": "full", "documents": docs["n"] if docs else 0,
            "message": f"Re-parses, re-chunks and re-embeds {docs['n'] if docs else 0} documents "
                       "(cached work is reused where possible)."}
