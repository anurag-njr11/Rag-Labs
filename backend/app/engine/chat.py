"""One chat turn: retrieve → rerank → pack prompt → generate → cite.

Emits events for streaming to the UI and records a run with its full trace.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, AsyncIterator

from .. import db, vault
from ..core import runs
from ..core.node import RunContext, build_node
from ..core.pipeline import index_config_hash
from ..ingest import builder
from ..llm import provider as llm
from ..nodes import verify as verify_node
from ..nodes.embed import ModelLoadError
from . import answer_cache, codecheck, compute, retrieval, sync

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


async def _verify(ctx: RunContext, verifier: Any, gen: Any, question: str, answer: str,
                  included: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the grounding check and record it as a trace step (a failed check → status "error", no retry)."""
    t = time.perf_counter()
    v = await verifier.check(gen, question, answer, included)
    tin, tout, cost = v.pop("tokens_in"), v.pop("tokens_out"), v.pop("cost_usd")
    ctx.emit("verify", ms=(time.perf_counter() - t) * 1000, tokens_in=tin, tokens_out=tout, cost_usd=cost,
             status=v["status"], grounded=v["grounded"], score=v["score"], claims=len(v["claims"]),
             unsupported=sum(c["supported"] == "no" for c in v["claims"]))
    return v


async def _execute(ctx: RunContext, verifier: Any, gen: Any, question: str, answer: str,
                   included: list[dict[str, Any]]) -> dict[str, Any]:
    """The code check, recorded as one trace step (plus the model calls it made)."""
    c = verifier.config
    t = time.perf_counter()
    res = await codecheck.check(gen, question, answer, [x["text"] for x in included], max_steps=c.max_steps,
                                allow_generated=c.allow_generated_tests, timeout_s=c.timeout_s)
    tin, tout = res.pop("tokens_in"), res.pop("tokens_out")
    ctx.emit("execution", ms=(time.perf_counter() - t) * 1000, tokens_in=tin, tokens_out=tout,
             cost_usd=llm.cost_usd(gen.provider, gen.model_name, tin, tout) if tin or tout else 0.0,
             status=res["status"], attempts=res.get("attempts", 0), test_source=res.get("test_source"))
    return res


async def _compute(ctx: RunContext, project_id: str, gen: Any, question: str) -> tuple[dict[str, Any] | None, bool]:
    """Route to a computation and run it -> (receipt or None, whether one was chosen). A receipt with
    attested False carries the failed checks (or the error); only an attested one is shown as the answer."""
    comps = await compute.load(project_id)
    if not comps:
        return None, False
    t = time.perf_counter()
    try:
        text, tin, tout = await gen.complete(compute.ROUTE_PROMPT.format(
            catalog=compute.catalog_text(list(comps.items())), question=question), 300)
    except llm.ProviderError as e:
        ctx.emit("compute_route", ms=(time.perf_counter() - t) * 1000, error=str(e), computation=None)
        return None, False
    cid, values = compute.parse_route(text)
    ctx.emit("compute_route", ms=(time.perf_counter() - t) * 1000, tokens_in=tin, tokens_out=tout,
             cost_usd=llm.cost_usd(gen.provider, gen.model_name, tin, tout),
             computation=comps[cid].name if cid in comps else None)
    if cid not in comps:
        return None, False
    t = time.perf_counter()
    try:
        receipt = await compute.run_checked(project_id, comps[cid], values)
    except compute.ComputeError as e:
        receipt = {"name": comps[cid].name, "parameters": values, "sql": comps[cid].sql, "attested": False,
                   "error": str(e), "checks": [], "result": None, "answer": None}
    receipt["computation_id"] = cid
    ctx.emit("compute", ms=(time.perf_counter() - t) * 1000, name=receipt["name"], attested=receipt["attested"],
             rows=len((receipt.get("result") or {}).get("rows") or []), error=receipt.get("error"))
    return receipt, True


async def answer(project_id: str, version: dict[str, Any], question: str,
                 source: str = "api", api_key_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
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
                                  question=question, source=source, api_key_id=api_key_id)
    trace: list[dict[str, Any]] = []
    ctx = RunContext(listener=lambda e: trace.append(
        {"seq": e.seq, "step": e.step, "ms": e.ms, "tokens_in": e.tokens_in,
         "tokens_out": e.tokens_out, "cost_usd": e.cost_usd, "payload": e.payload,
         "start_ms": e.start_ms}))
    yield {"type": "run", "run_id": run_id, "version": version["version"], "build_id": build["id"],
           "store": build["store_type"]}

    t0 = time.perf_counter()
    answer_text = ""
    result: dict[str, Any] = {}
    try:
        hit, cache_state = await answer_cache.lookup(ctx, project_id, cfg, question)
        if hit:
            cache_info = {k: hit[k] for k in ("question", "similarity", "created_at", "run_id")}
            results = hit.get("retrieved", [])
            result = {"retrieved": results, "citations": hit.get("citations", []), "cache": cache_info}
            yield {"type": "retrieval", "results": results, "trace": list(trace)}
            answer_text = hit["answer"]
            yield {"type": "token", "text": answer_text}
            latency = (time.perf_counter() - t0) * 1000
            await runs.finish_run(run_id, ctx, status="ok", answer=answer_text, result=result, latency_ms=latency)
            yield {"type": "done", "run_id": run_id, "answer": answer_text, "citations": result["citations"],
                   "retrieved": results, "trace": trace, "totals": {**ctx.totals, "latency_ms": round(latency, 1)},
                   "truncated": False, "verification": None, "cache": cache_info}
            return
        try:
            gen = build_node("generate", cfg["generate"])
        except KeyError:  # its provider was removed from Settings → Providers
            raise llm.ProviderError(
                f"LLM provider {cfg['generate']['type']!r} is no longer configured. Re-add it in "
                "Settings → Providers, or pick another model in Configure → Generate.") from None
        verifier = build_node("verify", cfg.get("verify") or {"type": "none"})
        computation, routed = None, False
        if (cfg.get("compute") or {}).get("type", "none") != "none":
            computation, routed = await _compute(ctx, project_id, gen, question)
            if computation and computation["attested"]:
                answer_text = computation["answer"]
                result = {"retrieved": [], "citations": [], "computation": computation}
                yield {"type": "retrieval", "results": [], "trace": list(trace)}
                yield {"type": "token", "text": answer_text}
                latency = (time.perf_counter() - t0) * 1000
                await runs.finish_run(run_id, ctx, status="ok", answer=answer_text, result=result,
                                      latency_ms=latency)
                yield {"type": "done", "run_id": run_id, "answer": answer_text, "citations": [], "retrieved": [],
                       "trace": trace, "totals": {**ctx.totals, "latency_ms": round(latency, 1)},
                       "truncated": False, "verification": None, "cache": None, "computation": computation}
                return
            if computation and cfg["compute"].get("on_fail") == "refuse":
                answer_text = (f"I couldn't verify that value: the computation \"{computation['name']}\" "
                               f"{'failed its checks' if computation.get('checks') else 'failed'}, so it isn't shown.")
                result = {"retrieved": [], "citations": [], "computation": computation}
                yield {"type": "token", "text": answer_text}
                latency = (time.perf_counter() - t0) * 1000
                await runs.finish_run(run_id, ctx, status="ok", answer=answer_text, result=result,
                                      latency_ms=latency)
                yield {"type": "done", "run_id": run_id, "answer": answer_text, "citations": [], "retrieved": [],
                       "trace": trace, "totals": {**ctx.totals, "latency_ms": round(latency, 1)},
                       "truncated": False, "verification": None, "cache": None, "computation": computation}
                return
        retries = verifier.config.max_retries if getattr(verifier.config, "on_fail", "") == "retry_with_more_context" else 0
        verification: dict[str, Any] | None = None
        execution: dict[str, Any] | None = None
        validate = verify_node.output_validation(cfg)
        attempt_cfg = cfg
        for attempt in range(retries + 1):
            if attempt:
                attempt_cfg = verify_node.more_context(attempt_cfg)
                answer_text = ""
                yield {"type": "retry", "attempt": attempt, "reason": "A claim in the answer isn't supported "
                       "by its sources, so it's answering again with more context."}
            results = await retrieval.retrieve(ctx, build=build, cfg=attempt_cfg, question=question)
            results = await retrieval.rerank(ctx, attempt_cfg, question, results)

            prompt = build_node("prompt", attempt_cfg["prompt"])
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

            usage: dict[str, Any] = {}
            t_gen = time.perf_counter()
            first_token_ms = None
            async for delta in gen.stream(built["messages"], usage):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t_gen) * 1000
                answer_text += delta
                if not validate:  # output validation sends the checked answer in one piece instead
                    yield {"type": "token", "text": delta}
            tin, tout = usage.get("tokens_in", 0), usage.get("tokens_out", 0)
            ctx.emit("generate", ms=(time.perf_counter() - t_gen) * 1000, tokens_in=tin, tokens_out=tout,
                     cost_usd=llm.cost_usd(gen.provider, gen.model_name, tin, tout),
                     provider=gen.provider, model=gen.model_name,
                     first_token_ms=round(first_token_ms or 0, 1), finish_reason=usage.get("finish_reason"),
                     reasoning_tokens=usage.get("reasoning_tokens"),
                     reasoning_effort=gen.config.reasoning_effort)

            if isinstance(verifier, verify_node.ExecutionCheck):
                yield {"type": "verifying", "what": "code"}
                execution = await _execute(ctx, verifier, gen, question, answer_text, built["included"])
                answer_text = execution.pop("answer")
                yield {"type": "execution", "execution": execution}
                break
            if not isinstance(verifier, verify_node.GroundingCheck):
                break
            yield {"type": "verifying"}
            verification = await _verify(ctx, verifier, gen, question, answer_text, built["included"])
            verification["attempt"] = attempt
            yield {"type": "verify", "verification": verification}
            if verification["grounded"] is not False:
                break

        if validate:
            with ctx.timed("output_validation") as t:
                answer_text, removed = verify_node.filter_unsourced(
                    answer_text, [c["text"] for c in built["included"]])
                t["removed"] = len(removed)
                t["items"] = removed[:10]
            yield {"type": "token", "text": answer_text}
        citations = extract_citations(answer_text, built["included"])
        cited = {c["chunk_id"] for c in citations}
        for r in results:
            r["cited"] = r["id"] in cited
        if verification:
            for c in citations:
                c["support"] = verification["citations"].get(c["n"])
        result.update(citations=citations, retrieved=results, verification=verification, computation=computation,
                      execution=execution)
        latency = (time.perf_counter() - t0) * 1000
        await runs.finish_run(run_id, ctx, status="ok", answer=answer_text, result=result, latency_ms=latency)
        truncated = usage.get("finish_reason") == "length"
        # A question routed to a computation isn't cached: its data can change without the documents changing.
        unverified_code = execution is not None and execution["status"] == "unverified"
        if not truncated and not routed and not unverified_code and (
                verification is None or verification["grounded"] is not False):
            await answer_cache.store(project_id, cache_state, question, answer_text, result, run_id)
        yield {"type": "done", "run_id": run_id, "answer": answer_text, "citations": citations,
               "retrieved": results, "trace": trace, "totals": {**ctx.totals, "latency_ms": round(latency, 1)},
               "truncated": truncated, "verification": verification, "cache": None,
               "computation": computation, "execution": execution}
    except (asyncio.CancelledError, GeneratorExit):
        # The client stopped the answer (Stop button / closed tab). Record it —
        # shielded, because this task is being cancelled — then let it unwind.
        await asyncio.shield(runs.finish_run(
            run_id, ctx, status="aborted", answer=answer_text, error="Stopped before the answer finished",
            result=result, latency_ms=(time.perf_counter() - t0) * 1000))
        raise
    except Exception as e:
        msg = str(e) if isinstance(e, (llm.ProviderError, ChatError, ModelLoadError)) else f"{type(e).__name__}: {e}"
        msg = vault.redact(msg)
        await runs.finish_run(run_id, ctx, status="error", answer=answer_text, error=msg, result=result,
                              latency_ms=(time.perf_counter() - t0) * 1000)
        raise ChatError(msg) from e
