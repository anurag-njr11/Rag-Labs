"""Semantic answer cache: lookup before retrieval, store after a good answer (cache slot)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from .. import db
from ..core.cache import stable_hash
from ..core.node import RunContext, build_node
from ..core.pipeline import with_defaults
from ..nodes.cache import SemanticCache, guard_terms
from . import sync


async def scope_key(project_id: str, cfg: dict[str, Any]) -> str:
    """Answers are shared only under the same answer-relevant config and the same documents."""
    full = with_defaults(cfg)
    return stable_hash({"cfg": {k: v for k, v in full.items() if k != "cache"},
                        "corpus": await sync.corpus_sha(project_id)})


def _cutoff(ttl_hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat(timespec="seconds")


async def lookup(ctx: RunContext, project_id: str, cfg: dict[str, Any], question: str
                 ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """-> (hit row or None, context for `store`). Emits a `cache_lookup` trace step."""
    node = build_node("cache", cfg.get("cache") or {"type": "none"})
    if not isinstance(node, SemanticCache):
        return None, {}
    c = node.config
    t0 = time.perf_counter()
    scope = await scope_key(project_id, cfg)
    vec = np.asarray(await build_node("embed", cfg["embed"]).embed_query(question), dtype=np.float32)
    guard = guard_terms(question)
    rows = await db.fetch_all(
        "SELECT id, question, guard, vector, answer, result, run_id, created_at FROM answer_cache"
        " WHERE project_id=? AND scope_key=? AND created_at >= ? ORDER BY created_at DESC, id",
        (project_id, scope, _cutoff(c.ttl_hours)))
    best, best_sim = None, -1.0
    q = vec / (np.linalg.norm(vec) or 1.0)
    for r in rows:
        v = np.frombuffer(r["vector"], dtype=np.float32)
        if v.shape != q.shape:
            continue
        sim = float(v @ q / (np.linalg.norm(v) or 1.0))
        if sim > best_sim:
            best, best_sim = r, sim
    hit = best is not None and best_sim >= c.threshold and db.loads(best["guard"], []) == guard
    near_miss = best is not None and best_sim >= c.threshold and not hit
    ctx.emit("cache_lookup", ms=(time.perf_counter() - t0) * 1000, hit=hit, entries=len(rows),
             similarity=round(best_sim, 4) if best is not None else None, threshold=c.threshold,
             **({"guard_blocked": True} if near_miss else {}))
    state = {"scope": scope, "vector": vec, "guard": guard, "config": c}
    if not hit:
        return None, state
    async with db.tx() as tx:
        await tx.execute("UPDATE answer_cache SET hits = hits + 1 WHERE id=?", (best["id"],))
    return {"id": best["id"], "question": best["question"], "answer": best["answer"],
            "similarity": round(best_sim, 4), "created_at": best["created_at"], "run_id": best["run_id"],
            **db.loads(best["result"], {})}, state


async def store(project_id: str, state: dict[str, Any], question: str, answer: str,
                result: dict[str, Any], run_id: str) -> None:
    """Remember a finished answer (callers skip truncated or not-grounded ones), then prune."""
    if not state or not answer.strip():
        return
    c = state["config"]
    async with db.tx() as tx:
        await tx.execute(
            "INSERT INTO answer_cache (id, project_id, scope_key, question, guard, vector, answer, result,"
            " run_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (db.new_id(), project_id, state["scope"], question, db.dumps(state["guard"]),
             state["vector"].astype(np.float32).tobytes(), answer,
             db.dumps({"citations": result.get("citations", []), "retrieved": result.get("retrieved", [])}),
             run_id, db.now_iso()))
        await tx.execute("DELETE FROM answer_cache WHERE project_id=? AND scope_key=? AND created_at < ?",
                         (project_id, state["scope"], _cutoff(c.ttl_hours)))
        await tx.execute(
            "DELETE FROM answer_cache WHERE id IN (SELECT id FROM answer_cache WHERE project_id=? AND scope_key=?"
            " ORDER BY created_at DESC, id LIMIT -1 OFFSET ?)", (project_id, state["scope"], c.max_entries))


async def stats(project_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT COUNT(*) AS entries, COALESCE(SUM(hits), 0) AS hits FROM answer_cache"
                             " WHERE project_id=?", (project_id,))
    return {"entries": row["entries"], "hits": row["hits"]}


async def clear(project_id: str) -> int:
    async with db.tx() as tx:
        cur = await tx.execute("DELETE FROM answer_cache WHERE project_id=?", (project_id,))
        return cur.rowcount
