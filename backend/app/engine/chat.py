"""One chat turn: retrieve → rerank → pack prompt → generate → cite.

Emits events for streaming to the UI and records a run with its full trace.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, AsyncIterator

from .. import db
from ..core import runs
from ..core.node import RunContext, build_node
from ..core.pipeline import index_config_hash
from ..ingest import builder
from ..llm import provider as llm
from . import retrieval, sync

_CITE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORDS = re.compile(r"\w+")


class ChatError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


def _best_span(claim: str, text: str) -> tuple[int, int] | None:
    """The sentence in `text` sharing the most words with `claim`."""
    claim_words = {w.lower() for w in _WORDS.findall(claim) if len(w) > 2}
    if not claim_words:
        return None
    best, best_score, pos = None, 0.0, 0
    for part in _SENT.split(text):
        start = text.find(part, pos)
        if start < 0:
            continue
        pos = start + len(part)
        words = {w.lower() for w in _WORDS.findall(part) if len(w) > 2}
        if not words:
            continue
        score = len(words & claim_words) / len(words | claim_words)
        if score > best_score:
            best, best_score = (start, start + len(part)), score
    return best if best_score >= 0.08 else None


def extract_citations(answer: str, included: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cites: dict[int, dict[str, Any]] = {}
    for m in _CITE.finditer(answer):
        # The claim is the sentence the marker closes.
        before = answer[: m.start()].rstrip()
        # Drop citation markers already in the sentence so they don't count as words.
        claim = _CITE.sub("", _SENT.split(before)[-1]) if before else ""
        for n in (int(x) for x in re.split(r"\s*[,;]\s*", m.group(1))):
            if not 1 <= n <= len(included):
                continue
            c = included[n - 1]
            entry = cites.setdefault(n, {
                "n": n, "chunk_id": c["id"], "document_id": c["document_id"], "document": c["document"],
                "page_start": c["page_start"], "page_end": c["page_end"],
                "heading_path": c["heading_path"], "spans": [],
            })
            span = _best_span(claim, c["text"])
            if span and list(span) not in entry["spans"]:
                entry["spans"].append(list(span))
    return [cites[n] for n in sorted(cites)]


async def ensure_ready(project_id: str, cfg: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Yield status events while the index for `cfg` is brought up to date."""
    build = await db.fetch_one(
        "SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?",
        (project_id, index_config_hash(cfg)),
    )
    if build and await builder.build_is_synced(build):
        return
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    if not docs or docs["n"] == 0:
        raise ChatError("This project has no documents yet. Add some on the Documents tab.", "no_documents")
    job = sync.start_sync(project_id, cfg)
    yield {"type": "status", "message": "Updating the index before answering…", "job_id": job.id}
    assert job._task is not None
    await job._task
    if job.status != "done":
        raise ChatError(f"Index build failed: {job.error}", "build_failed")


async def answer(project_id: str, version: dict[str, Any], question: str) -> AsyncIterator[dict[str, Any]]:
    cfg = sync.version_config(version)
    question = question.strip()
    if not question:
        raise ChatError("Ask a question.", "empty")

    async for ev in ensure_ready(project_id, cfg):
        yield ev
    build = await db.fetch_one(
        "SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?",
        (project_id, index_config_hash(cfg)),
    )
    assert build is not None

    run_id = await runs.start_run(project_id=project_id, version_id=version["id"], build_id=build["id"],
                                  question=question)
    trace: list[dict[str, Any]] = []
    ctx = RunContext(listener=lambda e: trace.append(
        {"seq": e.seq, "step": e.step, "ms": e.ms, "tokens_in": e.tokens_in,
         "tokens_out": e.tokens_out, "cost_usd": e.cost_usd, "payload": e.payload}))
    yield {"type": "run", "run_id": run_id, "version": version["version"], "build_id": build["id"],
           "store": build["store_type"]}

    t0 = time.perf_counter()
    answer_text = ""
    result: dict[str, Any] = {}
    try:
        results = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=question)
        results = await retrieval.rerank(ctx, cfg, question, results)

        prompt = build_node("prompt", cfg["prompt"])
        with ctx.timed("prompt") as t:
            built = prompt.build(question, results)
            t["included"] = len(built["included"])
            t["dropped"] = len(built["dropped"])
        included_ids = [c["id"] for c in built["included"]]
        for r in results:
            r["in_context"] = r["id"] in included_ids
            r["context_n"] = included_ids.index(r["id"]) + 1 if r["in_context"] else None
        result = {"retrieved": results, "messages": built["messages"]}
        yield {"type": "retrieval", "results": results, "trace": list(trace)}

        gen = build_node("generate", cfg["generate"])
        usage: dict[str, Any] = {}
        t_gen = time.perf_counter()
        first_token_ms = None
        async for delta in gen.stream(built["messages"], usage):
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - t_gen) * 1000
            answer_text += delta
            yield {"type": "token", "text": delta}
        tin, tout = usage.get("tokens_in", 0), usage.get("tokens_out", 0)
        ctx.emit("generate", ms=(time.perf_counter() - t_gen) * 1000, tokens_in=tin, tokens_out=tout,
                 cost_usd=llm.cost_usd(gen.provider, gen.model_name, tin, tout),
                 provider=gen.provider, model=gen.model_name,
                 first_token_ms=round(first_token_ms or 0, 1), finish_reason=usage.get("finish_reason"),
                 reasoning_tokens=usage.get("reasoning_tokens"),
                 reasoning_effort=gen.config.reasoning_effort)

        citations = extract_citations(answer_text, built["included"])
        cited = {c["chunk_id"] for c in citations}
        for r in results:
            r["cited"] = r["id"] in cited
        result.update(citations=citations, retrieved=results)
        latency = (time.perf_counter() - t0) * 1000
        await runs.finish_run(run_id, ctx, status="ok", answer=answer_text, result=result, latency_ms=latency)
        yield {"type": "done", "run_id": run_id, "answer": answer_text, "citations": citations,
               "retrieved": results, "trace": trace, "totals": {**ctx.totals, "latency_ms": round(latency, 1)},
               "truncated": usage.get("finish_reason") == "length"}
    except (asyncio.CancelledError, GeneratorExit):
        # The client stopped the answer (Stop button / closed tab). Record it —
        # shielded, because this task is being cancelled — then let it unwind.
        await asyncio.shield(runs.finish_run(
            run_id, ctx, status="aborted", answer=answer_text, error="Stopped before the answer finished",
            result=result, latency_ms=(time.perf_counter() - t0) * 1000))
        raise
    except Exception as e:
        msg = str(e) if isinstance(e, (llm.ProviderError, ChatError)) else f"{type(e).__name__}: {e}"
        await runs.finish_run(run_id, ctx, status="error", answer=answer_text, error=msg, result=result,
                              latency_ms=(time.perf_counter() - t0) * 1000)
        raise ChatError(msg) from e
