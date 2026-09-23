"""Query-time retrieval: dense, keyword and exact paths, fusion, MMR, rerank."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import numpy as np

from .. import db
from ..core.node import RunContext, build_node, get_spec
from ..core.pipeline import PipelineConfig, default_for
from ..ingest import lookup
from ..nodes import retrieve as R
from . import stores

_STOP = set("""a an and are as at be but by can do does for from how i if in into is it its me my of on or
so that the their them then there these this to was what when where which who why will with you your""".split())
_WORD = re.compile(r"\w+", re.UNICODE)


def fts_query(question: str) -> str | None:
    words = [w.lower() for w in _WORD.findall(question)]
    terms = list(dict.fromkeys(w for w in words if w not in _STOP and len(w) > 1))[:32]
    if not terms:
        return None
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


async def keyword_search(build_id: str, question: str, limit: int) -> R.Ranked:
    q = fts_query(question)
    if q is None:
        return []
    rows = await db.fetch_all(
        "SELECT chunk_id, bm25(chunks_fts) AS s FROM chunks_fts"
        " WHERE chunks_fts MATCH ? AND build_id = ? ORDER BY s, chunk_id LIMIT ?",
        (q, build_id, limit),
    )
    return [(r["chunk_id"], -float(r["s"])) for r in rows]


async def exact_search(build_id: str, question: str, limit: int) -> tuple[R.Ranked, dict[str, list[str]]]:
    keys = lookup.query_keys(question)
    if not keys:
        return [], {}
    wanted = {k for _, k in keys}
    rows = await db.fetch_all(
        f"SELECT chunk_id, kind, key FROM lookup_index WHERE build_id=? AND key IN ({','.join('?' * len(wanted))})",
        (build_id, *sorted(wanted)),
    )
    scores: dict[str, float] = {}
    seen: set[tuple[str, str, str]] = set()
    matched: dict[str, set[str]] = {}
    for r in rows:
        # Count each (kind, key) once per chunk: the same key can match both as a
        # symbol in the text and as the section's heading, and both should count.
        k = (r["chunk_id"], r["kind"], r["key"])
        if k in seen:
            continue
        seen.add(k)
        label = f"heading:{r['key']}" if r["kind"] == "heading" else r["key"]
        matched.setdefault(r["chunk_id"], set()).add(label)
        scores[r["chunk_id"]] = scores.get(r["chunk_id"], 0.0) + lookup.KIND_WEIGHT[r["kind"]]
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return ranked, {cid: sorted(matched[cid]) for cid, _ in ranked}


async def load_chunks(ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = await db.fetch_all(
        f"SELECT c.id, c.document_id, c.ordinal, c.text, c.text_sha, c.token_count, c.is_table,"
        f" c.page_start, c.page_end, c.heading_path, d.filename AS document, d.source_url"
        f" FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id IN ({','.join('?' * len(ids))})",
        tuple(ids),
    )
    return {r["id"]: r for r in rows}


async def chunk_vectors(chunks: dict[str, dict[str, Any]], embed_key: str) -> dict[str, np.ndarray]:
    shas = {c["text_sha"]: cid for cid, c in chunks.items()}
    if not shas:
        return {}
    rows = await db.fetch_all(
        f"SELECT text_sha, vector FROM vector_cache WHERE embed_key=? AND text_sha IN ({','.join('?' * len(shas))})",
        (embed_key, *shas),
    )
    by_sha = {r["text_sha"]: np.frombuffer(r["vector"], dtype=np.float32) for r in rows}
    return {cid: by_sha[sha] for sha, cid in shas.items() if sha in by_sha}


def store_params(cfg: PipelineConfig) -> Any:
    vs = cfg["vector_store"]
    spec = get_spec("vector_store", vs["type"])
    return spec.cls.Config(**{k: v for k, v in {**default_for("vector_store", vs["type"]), **vs}.items()
                               if k != "type"})


async def retrieve(ctx: RunContext, *, build: dict[str, Any], cfg: PipelineConfig,
                   question: str) -> list[dict[str, Any]]:
    retriever = build_node("retrieve", cfg["retrieve"])
    rc: R.RetrieveConfig = retriever.config  # type: ignore[assignment]
    paths = retriever.paths
    lists: dict[str, R.Ranked] = {}
    exact_keys: dict[str, list[str]] = {}
    query_vec: np.ndarray | None = None
    embedder = build_node("embed", cfg["embed"])

    if "dense" in paths or rc.mmr:
        with ctx.timed("embed_query", model=getattr(embedder.config, "model", "")):
            query_vec = await embedder.embed_query(question)

    async def dense() -> None:
        store = await stores.open_store(build)
        with ctx.timed("dense_search", store=build["store_type"]) as t:
            hits = await asyncio.to_thread(store.search, query_vec, rc.candidates, store_params(cfg))
            if rc.min_score:
                hits = [h for h in hits if h[1] >= rc.min_score]
            t["hits"] = len(hits)
            t["exact"] = store.is_exact()
        lists["dense"] = hits

    async def keyword() -> None:
        with ctx.timed("keyword_search") as t:
            lists["keyword"] = await keyword_search(build["id"], question, rc.candidates)
            t["hits"] = len(lists["keyword"])

    async def exact() -> None:
        with ctx.timed("exact_search") as t:
            lists["exact"], found = await exact_search(build["id"], question, rc.candidates)
            exact_keys.update(found)
            t["hits"] = len(lists["exact"])

    tasks = {"dense": dense, "keyword": keyword, "exact": exact}
    await asyncio.gather(*(tasks[p]() for p in paths))

    weights = {"dense": rc.dense_weight, "keyword": rc.keyword_weight, "exact": rc.exact_weight}
    with ctx.timed("fuse", method=rc.fusion if len(paths) > 1 else "none") as t:
        if len(paths) == 1:
            fused = lists.get(paths[0], [])
        elif rc.fusion == "rrf":
            fused = R.rrf(lists, weights, rc.rrf_k)
        else:
            fused = R.weighted(lists, weights)
        t["candidates"] = len(fused)

    pinned: list[str] = []
    if rc.pin_definitions and "exact" in lists:
        # Exact-path order already puts heading matches (weight 6) first.
        pinned = [cid for cid, _ in lists["exact"]
                  if any(k.startswith("heading:") for k in exact_keys.get(cid, []))]
        if pinned:
            score = dict(fused)
            top_score = fused[0][1] if fused else 0.0
            fused = [(cid, max(score.get(cid, 0.0), top_score)) for cid in pinned] +                     [(cid, s) for cid, s in fused if cid not in set(pinned)]
            ctx.emit("pin", pinned=len(pinned))

    if rc.mmr and fused:
        pool = fused[: max(rc.top_k * 4, 20)]
        pool_chunks = await load_chunks([cid for cid, _ in pool])
        with ctx.timed("mmr", lambda_=rc.mmr_lambda):
            vecs = await chunk_vectors(pool_chunks, embedder.embed_key())
            top = R.mmr(pool, vecs, query_vec, rc.top_k, rc.mmr_lambda)  # type: ignore[arg-type]
    else:
        top = fused[: rc.top_k]

    chunks = await load_chunks([cid for cid, _ in top])
    per_path = {p: {cid: (rank, score) for rank, (cid, score) in enumerate(lst, start=1)}
                for p, lst in lists.items()}
    results = []
    for rank, (cid, score) in enumerate(top, start=1):
        c = chunks.get(cid)
        if c is None:  # stale id (document removed mid-query)
            continue
        scores = {p: round(per_path[p][cid][1], 5) for p in per_path if cid in per_path[p]}
        ranks = {p: per_path[p][cid][0] for p in per_path if cid in per_path[p]}
        results.append({
            **{k: c[k] for k in ("id", "document_id", "document", "source_url", "ordinal", "text",
                                 "token_count", "page_start", "page_end", "heading_path")},
            "is_table": bool(c["is_table"]),
            "rank": rank,
            "retrieval_rank": rank,
            "score": round(score, 6),
            "scores": scores,
            "ranks": ranks,
            "found_by": sorted(scores),
            "exact_keys": exact_keys.get(cid, []),
            "pinned": cid in pinned,
        })
    return results


async def rerank(ctx: RunContext, cfg: PipelineConfig, question: str,
                 results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node = build_node("rerank", cfg["rerank"])
    if cfg["rerank"]["type"] == "none" or not results:
        return results
    with ctx.timed("rerank", model=node.config.model) as t:
        ranked = await node.rerank(question, [(r["id"], r["text"]) for r in results])
        t["kept"] = len(ranked)
    by_id = {r["id"]: r for r in results}
    out = []
    for rank, (cid, score) in enumerate(ranked, start=1):
        r = dict(by_id[cid])
        r["scores"] = {**r["scores"], "rerank": round(score, 5)}
        r["rank"] = rank
        out.append(r)
    return out
