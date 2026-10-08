"""Agentic retrieval (FR-3.1) with optional context offloading (FR-3.2).

plan → search → read → keep, as one option in the retrieve slot. The plain question is searched
first; then an LLM planner (the Generate model, temperature 0) chooses each step: more searches,
reading passages in full (offload mode), or done — naming the passages that answer the question.
Answer writing stays with the normal prompt + generate slots, so the leaderboard compares
retrieval strategies on equal terms.

Every search runs through the ordinary retriever (`search_mode`), so its trace steps, scores and
`found_by` badges appear as usual. Passages get short aliases (c1, c2, …) in the planner's view:
cheaper than chunk ids, and an invented alias is simply ignored.
"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Any

from ..core.cache import stable_hash
from ..core.node import RunContext, build_node
from ..llm import provider as llm
from ..nodes import retrieve as R

FULL_CHARS = 1200  # passage text shown when not offloading, and per `read`
SNIPPET_CHARS = 160  # offload mode: what a reference shows
MAX_QUERIES = 3  # per search step
MAX_READS = 5  # per read step

PLANNER = """You are the retrieval planner for a document question-answering system. Find the passages
that answer the question; another model writes the answer from the passages you keep.

Reply with JSON only — exactly one action:
{{"action": "search", "queries": ["...", "..."]}}  up to {max_queries} short search queries, e.g. one per part
                                                    of the question, or reworded after a miss
{read_action}{{"action": "done", "keep": ["c3", "c1"]}}            the passages that answer it, most useful first;
                                                    [] if nothing does

Search for each part of the question that the passages don't cover yet. Never repeat a query.
Stop as soon as the evidence is there. Steps left after this one: {left}.

Question: {question}

Searches so far: {searches}

Passages found so far{view}:
{passages}"""

READ_ACTION = ('{{"action": "read", "ids": ["c2", "c5"]}}            see up to {max_reads} passages in full '
               '(you see only a snippet of each)\n')

# Agent runs are LLM-driven, so they're cached per (config minus top_k, question), like query
# expansions: the eval's deep pass then re-ranks the same run instead of paying for a new one.
# ponytail: process-lifetime dict cleared when full; persist it if agent cost shows up in sweeps.
_runs: dict[str, tuple[list[str], dict[str, dict[str, Any]], float | None, list[dict[str, Any]], int, float]] = {}


def _search_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """The plain retriever each search runs through."""
    rc = cfg["retrieve"]
    inner = copy.deepcopy(cfg)
    inner["retrieve"] = {k: v for k, v in rc.items()
                         if k not in ("search_mode", "max_steps", "per_search_k", "offload")}
    inner["retrieve"].update(type=rc["search_mode"], top_k=rc["per_search_k"], query_expansion="none",
                             context_window=0, mmr=False)
    return inner


def parse_action(text: str) -> dict[str, Any] | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        a = json.loads(m.group(0) if m else text)
    except (ValueError, AttributeError):
        return None
    return a if isinstance(a, dict) and a.get("action") in ("search", "read", "done") else None


def _view(alias: str, r: dict[str, Any], full: bool) -> str:
    where = r["document"] + (f" › {r['heading_path']}" if r.get("heading_path") else "")
    text = " ".join(r["text"].split())
    cut = FULL_CHARS if full else SNIPPET_CHARS
    return f"[{alias}] {where}\n{text[:cut]}{'…' if len(text) > cut else ''}"


async def retrieve(ctx: RunContext, *, build: dict[str, Any], cfg: dict[str, Any],
                   question: str) -> list[dict[str, Any]]:
    from . import retrieval  # circular: retrieval dispatches here

    rc = build_node("retrieve", cfg["retrieve"]).config
    key = stable_hash([{k: v for k, v in cfg["retrieve"].items() if k not in ("top_k", "candidates")},
                       {s: cfg[s] for s in ("embed", "vector_store", "generate") if s in cfg},
                       build["id"], question])
    if key in _runs:
        order, found, cost, steps, tokens, ms = _runs[key]
        ctx.emit("agent", cached=True, steps=len(steps), uncached_cost_usd=cost, uncached_tokens=tokens,
                 uncached_ms=ms)
    else:
        n0, t0 = len(ctx.events), time.perf_counter()
        order, found, cost, steps = await _run(ctx, retrieval, build, cfg, rc, question)
        tokens = sum(e.tokens_in + e.tokens_out for e in ctx.events[n0:])
        if len(_runs) >= 512:
            _runs.clear()
        _runs[key] = (order, found, cost, steps, tokens, (time.perf_counter() - t0) * 1000)

    results = []
    for rank, cid in enumerate(order[:rc.top_k], start=1):
        r = dict(found[cid])
        r.update(rank=rank, retrieval_rank=rank, score=round(1.0 / (rc.rrf_k + rank), 6))
        results.append(r)
    if rc.context_window and results:
        with ctx.timed("context_window", window=rc.context_window) as t:
            await retrieval.add_neighbours(build["id"], results, rc.context_window)
            t["chunks_added"] = sum(len(r["window"]) - 1 for r in results)
    return results


async def _run(ctx: RunContext, retrieval: Any, build: dict[str, Any], cfg: dict[str, Any], rc: Any,
               question: str) -> tuple[list[str], dict[str, dict[str, Any]], float | None, list[dict[str, Any]]]:
    """-> (chunk ids best first, chunk by id, list cost of the planner calls, step log)."""
    inner = _search_cfg(cfg)
    gen = build_node("generate", cfg["generate"])
    found: dict[str, dict[str, Any]] = {}  # chunk id -> retrieved chunk, in first-found order
    alias: dict[str, str] = {}  # "c1" -> chunk id
    per_search: list[R.Ranked] = []
    searches: list[str] = []
    read: set[str] = set()
    keep: list[str] | None = None
    steps: list[dict[str, Any]] = []
    cost: float | None = 0.0

    async def search(q: str) -> None:
        searches.append(q)
        hits = await retrieval.retrieve(ctx, build=build, cfg=inner, question=q)
        per_search.append([(h["id"], h["score"]) for h in hits])
        for h in hits:
            if h["id"] not in found:
                found[h["id"]] = h
                alias[f"c{len(alias) + 1}"] = h["id"]

    await search(question)
    for step in range(rc.max_steps):
        by_id = {cid: a for a, cid in alias.items()}
        passages = "\n\n".join(_view(by_id[cid], r, full=not rc.offload or cid in read)
                               for cid, r in found.items()) or "(none)"
        prompt = PLANNER.format(
            max_queries=MAX_QUERIES, left=rc.max_steps - step - 1, question=question,
            read_action=READ_ACTION.format(max_reads=MAX_READS) if rc.offload else "",
            searches="; ".join(f'"{s}"' for s in searches),
            view=" (snippets — read to see more)" if rc.offload else "", passages=passages)
        t0 = time.perf_counter()
        try:
            text, tin, tout = await gen.complete(prompt, 400)
        except llm.ProviderError as e:  # keep what the searches found
            ctx.emit("agent", ms=(time.perf_counter() - t0) * 1000, turn=step + 1, action="error", error=str(e))
            steps.append({"action": "error"})
            break
        c = llm.cost_usd(gen.provider, gen.model_name, tin, tout)
        cost = None if cost is None or c is None else cost + c
        action = parse_action(text) or {"action": "done", "invalid": True}
        info: dict[str, Any] = {"turn": step + 1, "action": action["action"], "context_chars": len(prompt),
                                "offload": rc.offload}
        if action["action"] == "search":
            qs = [str(q).strip() for q in action.get("queries") or [] if str(q).strip()]
            qs = [q for q in dict.fromkeys(qs) if q.lower() not in {s.lower() for s in searches}][:MAX_QUERIES]
            info["queries"] = qs
        elif action["action"] == "read":
            ids = [alias[a] for a in action.get("ids") or [] if a in alias][:MAX_READS]
            info["read"] = len(ids)
        else:
            keep = [alias[a] for a in dict.fromkeys(action.get("keep") or []) if a in alias]
            info["keep"] = len(keep)
            if action.get("invalid"):
                info["invalid_reply"] = True
        ctx.emit("agent", ms=(time.perf_counter() - t0) * 1000, tokens_in=tin, tokens_out=tout, cost_usd=c,
                 provider=gen.provider, model=gen.model_name, **info)
        steps.append(info)
        if action["action"] == "done":
            break
        if action["action"] == "search":
            if not info["queries"]:
                break  # nothing new to look for
            for q in info["queries"]:
                await search(q)
        else:
            read.update(ids)
    # Kept passages first (the planner's order), then the rest as the searches ranked them, taking
    # turns across searches so each one's best hits come before any search's long tail.
    rest = [cid for cid, _ in R.interleave(per_search, 60) if cid not in set(keep or [])]
    return [*(keep or []), *rest], found, cost, steps
