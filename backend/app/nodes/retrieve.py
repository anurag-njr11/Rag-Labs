"""Retrieve slot: find the chunks relevant to a question.

Up to three paths run — dense (the vector store), keyword (SQLite FTS5 BM25)
and exact (normalised error/symbol lookup) — and their ranked lists are fused.
There is no router deciding which path to use: every enabled path always
runs, and fusion lets the best evidence win. The IO lives in
engine/retrieval.py; this module holds config and pure ranking math.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from ..core.node import Node, NodeConfig, register, ui_field

Ranked = list[tuple[str, float]]  # (chunk_id, score), best first

MODE_PATHS = {
    "dense": ("dense",),
    "keyword": ("keyword",),
    "hybrid": ("dense", "keyword"),
    "fused": ("dense", "keyword", "exact"),
}


class RetrieveConfig(NodeConfig):
    top_k: int = ui_field(8, ge=1, le=50, title="Results (top-k)",
                          description="How many chunks to pass on (before reranking, if on).")
    fusion: Literal["rrf", "weighted"] = ui_field(
        "rrf", title="Fusion method",
        description="How ranked lists from several paths combine. RRF uses ranks only; weighted uses normalised scores.",
    )
    rrf_k: int = ui_field(60, ge=1, le=1000, advanced=True, title="RRF constant (k)",
                          description="Higher flattens the advantage of top ranks.")
    dense_weight: float = ui_field(1.0, ge=0, le=5, advanced=True, title="Dense weight")
    keyword_weight: float = ui_field(1.0, ge=0, le=5, advanced=True, title="Keyword weight")
    exact_weight: float = ui_field(1.5, ge=0, le=5, advanced=True, title="Exact-match weight")
    candidates: int = ui_field(40, ge=5, le=500, advanced=True, title="Candidates per path",
                               description="How many results each path contributes before fusion.")
    min_score: float = ui_field(0.0, ge=-1, le=1, advanced=True, title="Minimum similarity",
                                description="Drop dense results below this similarity. 0 = keep all.")
    pin_definitions: bool = ui_field(
        True, title="Pin defining sections",
        description="Put sections whose heading exactly names the error or symbol you asked about first "
                    "(fused mode). Fusion otherwise only sees ranks, not how exact a match was.",
    )
    mmr: bool = ui_field(False, title="Diversify (MMR)",
                         description="Maximal Marginal Relevance: prefer results that aren't near-duplicates.")
    mmr_lambda: float = ui_field(0.7, ge=0, le=1, advanced=True, title="MMR relevance weight",
                                 description="1 = pure relevance, 0 = pure diversity.")
    query_expansion: Literal["none", "multi_query", "hyde", "decompose"] = ui_field(
        "none", title="Query expansion",
        description="multi_query: the Generate model rewrites the question a few ways, each is searched, "
                    "results fused (RRF). hyde: it writes a hypothetical answer, which the dense path searches "
                    "with instead of the question. decompose: it splits a multi-part question into "
                    "sub-questions, each is searched, and the results take turns in the top-k so every part "
                    "gets evidence. One extra LLM call per question; falls back to the plain question if the "
                    "call fails.",
    )
    expansion_queries: int = ui_field(3, ge=1, le=5, advanced=True, title="Rewrites / sub-questions",
                                      description="multi_query: how many rewrites to search with. "
                                                  "decompose: the most sub-questions to split into.")
    okf_policy: bool = ui_field(
        False, title="Use document metadata (OKF)",
        description="Leave out documents past their stale_after date, halve the score of documents marked "
                    "deprecated, and on equal scores prefer sources verified by a human. Set per document in "
                    "Markdown front matter, an OKF bundle, or the Documents tab.")
    adapter: str = ui_field(
        "", advanced=True, title="Embedding adapter",
        description="A query-side adapter trained on your eval set (Evaluate → Embedding adapter → Use). Empty = "
                    "none. It must have been trained for this embedding model; otherwise it's skipped (the trace "
                    "says so).")
    context_window: int = ui_field(
        0, ge=0, le=3, title="Context window (neighbours)",
        description="Add this many neighbouring chunks on each side (same document, in order) to every "
                    "result before reranking and the prompt. Sentence-window / auto-merging style: search "
                    "small, answer with more context. 0 = off.",
    )


class BaseRetriever(Node):
    Config = RetrieveConfig
    paths: tuple[str, ...] = ()


@register("retrieve", "fused", title="Fused (dense + keyword + exact)",
          description="Best default. Adds exact matching for error messages and code symbols.")
class FusedRetriever(BaseRetriever):
    paths = MODE_PATHS["fused"]


@register("retrieve", "hybrid", title="Hybrid (dense + keyword)",
          description="Meaning-based search combined with keyword (BM25) search.")
class HybridRetriever(BaseRetriever):
    paths = MODE_PATHS["hybrid"]


@register("retrieve", "dense", title="Dense (vectors only)",
          description="Pure semantic search through the vector store.")
class DenseRetriever(BaseRetriever):
    paths = MODE_PATHS["dense"]


@register("retrieve", "keyword", title="Keyword (BM25 only)",
          description="Classic full-text search. No embeddings used at query time.")
class KeywordRetriever(BaseRetriever):
    paths = MODE_PATHS["keyword"]


class AgenticConfig(RetrieveConfig):
    search_mode: Literal["fused", "hybrid", "dense", "keyword"] = ui_field(
        "fused", title="Each search uses",
        description="The retriever the agent's searches run through.")
    max_steps: int = ui_field(3, ge=1, le=6, title="Step budget",
                              description="Most planner LLM calls per question. Each step can search or read; "
                                          "it stops early once it has the evidence.")
    per_search_k: int = ui_field(5, ge=1, le=20, title="Results per search",
                                 description="How many passages each search adds to what the agent has seen.")
    offload: bool = ui_field(
        False, title="Context offloading",
        description="Show the agent short references (document › heading + a snippet) instead of full passages; "
                    "it reads in full only what it asks for. Keeps the planner's context small.")


@register("retrieve", "agentic", title="Agentic (plan → search → read)",
          description="An LLM planner searches in steps — splitting the question, refining queries, reading "
                      "passages — and keeps the evidence that answers it. Several LLM calls per question: "
                      "slower and costlier; compare it against hybrid + rerank on the leaderboard.")
class AgenticRetriever(BaseRetriever):
    Config = AgenticConfig

    @property
    def paths(self) -> tuple[str, ...]:  # type: ignore[override]
        return MODE_PATHS[self.config.search_mode]


# --- ranking math -----------------------------------------------------------


def _sorted(scores: dict[str, float]) -> Ranked:
    # Deterministic: score desc, then chunk id.
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def rrf(lists: dict[str, Ranked], weights: dict[str, float], k: int) -> Ranked:
    scores: dict[str, float] = {}
    for path, ranked in lists.items():
        w = weights.get(path, 1.0)
        for rank, (cid, _) in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank)
    return _sorted(scores)


def interleave(groups: list[Ranked], k: int) -> Ranked:
    """Query decomposition: take turns across the groups (question, sub-question 1, …), skipping
    chunks already taken, so every part of a multi-part question reaches the top-k. Fusion within a
    group rewards consensus; across groups, coverage matters more. Score = 1 / (k + merged rank)."""
    out: list[str] = []
    seen: set[str] = set()
    for i in range(max((len(g) for g in groups), default=0)):
        for g in groups:
            if i < len(g) and g[i][0] not in seen:
                seen.add(g[i][0])
                out.append(g[i][0])
    return [(cid, 1.0 / (k + rank)) for rank, cid in enumerate(out, start=1)]


def weighted(lists: dict[str, Ranked], weights: dict[str, float]) -> Ranked:
    scores: dict[str, float] = {}
    for path, ranked in lists.items():
        if not ranked:
            continue
        vals = [s for _, s in ranked]
        lo, hi = min(vals), max(vals)
        w = weights.get(path, 1.0)
        for cid, s in ranked:
            norm = 1.0 if hi == lo else (s - lo) / (hi - lo)
            scores[cid] = scores.get(cid, 0.0) + w * norm
    return _sorted(scores)


def mmr(ranked: Ranked, vectors: dict[str, np.ndarray], query: np.ndarray, k: int,
        lam: float) -> Ranked:
    """Re-order by Maximal Marginal Relevance. Chunks without a vector keep
    their relative position after the diversified ones."""
    have = [(cid, s) for cid, s in ranked if cid in vectors]
    missing = [(cid, s) for cid, s in ranked if cid not in vectors]
    if not have:
        return ranked[:k]
    q = query / (np.linalg.norm(query) or 1.0)
    vecs = {cid: v / (np.linalg.norm(v) or 1.0) for cid, v in ((c, vectors[c]) for c, _ in have)}
    rel = {cid: float(vecs[cid] @ q) for cid, _ in have}
    chosen: list[tuple[str, float]] = []
    pool = [cid for cid, _ in have]
    base = dict(have)
    while pool and len(chosen) < k:
        def score(cid: str) -> float:
            div = max((float(vecs[cid] @ vecs[c]) for c, _ in chosen), default=0.0)
            return lam * rel[cid] - (1 - lam) * div

        best = min(pool, key=lambda c: (-score(c), c))
        chosen.append((best, base[best]))
        pool.remove(best)
    return (chosen + missing)[:k]
