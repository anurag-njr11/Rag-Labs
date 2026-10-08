"""Auto-generated eval sets and retrieval scoring against them.

generate_set: sample chunks -> LLM writes (question, answer, evidence) per chunk ->
closed-book filter drops questions the model answers without any context.
run_eval: runs every kept question through a version's retrieve+rerank and
scores the rank of the first chunk containing the evidence.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import re
import time
from typing import Any

from .. import db, vault
from ..core import evalmetrics as M
from ..core.node import RunContext, TraceEvent, build_node
from ..core.pipeline import index_config_hash
from ..ingest.jobs import Job
from ..llm import provider as llm
from ..nodes.chunk import approx_tokens
from ..nodes.prompt import packed_text
from ..nodes.retrieve import dense_used
from ..nodes import verify as verify_node
from . import chat, codecheck, external, retrieval, stores, sync

GEN_BATCH = 5
VAL_BATCH = 10
GRADE_BATCH = 5
GRADE_CONTEXT_CHARS = 800
GENERIC_F1 = 0.6
DEEP_K = 50  # deep pass: top_k and candidates >= this; RunsPanel.tsx "not_retrieved" copy says "top 50"
_llm_slots = asyncio.Semaphore(3)


class EvalError(Exception):
    pass


GEN_SYSTEM = """You write evaluation questions for a document search system.
For each numbered passage, write ONE question a real user might ask that this passage answers.
Rules:
- The question must be answerable from that passage alone and be specific to it, not general knowledge.
- Phrase it the way a user would; do not copy more than 4 consecutive words from the passage.
- Never refer to "the passage", "the text", "the document" or "the author".
- "answer": the correct answer in at most 30 words.
- "evidence": copy, character for character, the one or two sentences from the passage that contain the answer.
- "facets": the 1 to 4 short facts a complete answer must state (a few words each), e.g. ["3 retries", "exponential backoff"].
- If a passage has no answerable factual content (navigation, table of contents, boilerplate), use an empty question.
Reply with JSON only: {"items": [{"passage": 1, "question": "...", "answer": "...", "evidence": "...", "facets": ["..."]}]}"""

VAL_SYSTEM = """Answer each question from your own general knowledge in at most 25 words.
You have no documents. If you do not know, answer "unknown".
Reply with JSON only: {"answers": [{"id": 1, "answer": "..."}]}"""


GRADE_SYSTEM = """You grade answers from a document question-answering system.
Each numbered item has the question, the reference answer, sometimes the required facts, the system's answer,
and the sources the system was given.
- "correct": "yes" if the system's answer states the reference answer's facts (wording may differ);
  "partial" if some facts are missing or vague; "no" if wrong, missing, or it says it doesn't know.
- "grounded": "yes" if every claim in the system's answer is supported by its sources;
  "partial" if some claims are not; "no" if it is mostly unsupported.
- "relevant": "yes" if the answer addresses the question asked; "partial" if it only partly does or drifts;
  "no" if it answers something else.
- "specificity": "ok" if its level of detail fits the question; "too_vague" if it is generic or hedged where the
  reference is specific; "too_verbose" if the answer is buried in detail nobody asked for.
- "facts": only when required facts are listed: one "yes" or "no" per fact, in order. Does the system's answer state it?
- "sources_relevant": one "yes" or "no" per source, in order. Does that source contain information useful for
  answering the question?
- "facts_in_sources": one "yes" or "no" per required fact, in order; when no facts are listed, a single value for the
  reference answer as a whole. Do the sources (not the system's answer) support it?
Reply with JSON only: {"results": [{"id": 1, "correct": "yes", "grounded": "yes", "relevant": "yes",
"specificity": "ok", "facts": ["yes", "no"], "sources_relevant": ["yes", "no", "yes"], "facts_in_sources": ["yes", "yes"]}]}"""
LEVELS = ("yes", "partial", "no")
SPECIFICITY = ("ok", "too_vague", "too_verbose")
MAX_FACETS = 4


def parse_json(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def llm_settings(cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    gen = cfg["generate"]
    provider = gen["type"]
    extra: dict[str, Any] = {}
    effort = gen.get("reasoning_effort", "none")
    if effort and effort != "default":
        extra["reasoning_effort"] = effort
    return provider, {"model": gen.get("model") or "", **extra}


async def complete(provider: str, opts: dict[str, Any], system: str, user: str) -> str:
    opts = {"temperature": 0.3, **opts}  # judge calls pass temperature=0 in opts
    if not opts["model"]:
        opts["model"] = await llm.resolve_model(provider, "chat")
    async def call() -> Any:
        try:
            return await llm.client(provider).chat.completions.create(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=4096, stream=False, **opts)
        except Exception as e:
            raise llm.friendly_error(provider, e) from e

    async with _llm_slots:
        resp = await llm.retrying(call)
    return resp.choices[0].message.content or ""


async def ready_build(project_id: str, cfg: dict[str, Any], job: Job) -> dict[str, Any]:
    try:
        async for ev in chat.ensure_ready(project_id, cfg):
            job.progress("index", message=ev.get("message", "Updating the index…"))
    except chat.ChatError as e:
        raise EvalError(str(e)) from e
    build = await db.fetch_one("SELECT * FROM index_builds WHERE project_id=? AND index_config_hash=?",
                               (project_id, index_config_hash(cfg)))
    if build is None or build["status"] != "ready":
        raise EvalError("The index for this version isn't ready.")
    return build


# --- generation ---------------------------------------------------------------

async def _generate_batch(provider: str, opts: dict[str, Any], batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts = []
    for i, c in enumerate(batch, start=1):
        where = f"{c['document']}" + (f" · {c['heading_path']}" if c.get("heading_path") else "")
        parts.append(f"### Passage {i} ({where})\n{c['text']}")
    raw = await complete(provider, opts, GEN_SYSTEM, "\n\n".join(parts))
    out = []
    for entry in (parse_json(raw) or {}).get("items", []):
        try:
            idx = int(entry.get("passage", 0)) - 1
        except (TypeError, ValueError):
            continue
        q = str(entry.get("question") or "").strip()
        if not (0 <= idx < len(batch)) or not q:
            continue
        out.append({"chunk": batch[idx], "question": q, "answer": str(entry.get("answer") or "").strip(),
                    "evidence": str(entry.get("evidence") or "").strip(), "facets": clean_facets(entry.get("facets"))})
    return out


def clean_facets(raw: Any) -> list[str]:
    """At most 4 short, non-empty, de-duplicated facts; anything else is dropped."""
    out: list[str] = []
    for f in raw if isinstance(raw, list) else []:
        f = str(f or "").strip()[:200]
        if f and f.lower() not in {x.lower() for x in out}:
            out.append(f)
    return out[:MAX_FACETS]


corpus_sha = sync.corpus_sha


async def _closed_book(provider: str, opts: dict[str, Any], questions: list[str]) -> dict[int, str]:
    user = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))
    raw = await complete(provider, opts, VAL_SYSTEM, user)
    answers: dict[int, str] = {}
    for a in (parse_json(raw) or {}).get("answers", []):
        try:
            answers[int(a.get("id")) - 1] = str(a.get("answer") or "")
        except (TypeError, ValueError):
            continue
    return answers


def check_candidate(cand: dict[str, Any], closed: str | None) -> str | None:
    """Reason to reject a generated item, or None to keep it."""
    ev = cand["evidence"]
    if len(M.tokens(ev)) < M.MIN_EVIDENCE_TOKENS or M.coverage(ev, cand["chunk"]["text"]) < 0.9:
        return "evidence not found in source"
    if not cand["answer"]:
        return "no answer"
    if closed is not None and M.token_f1(closed, cand["answer"]) >= GENERIC_F1:
        return "too generic: answerable without the documents"
    return None


async def gather_tolerant(coros: list, job: Job, stage: str) -> tuple[list[Any], list[Exception]]:
    results: list[Any] = [None] * len(coros)
    errors: list[Exception] = []
    done = 0

    async def one(i: int, coro: Any) -> None:
        nonlocal done
        try:
            results[i] = await coro
        except Exception as e:  # one failed batch shouldn't sink the set
            errors.append(e)
            job.log(str(e), level="warning")
        done += 1
        job.progress(stage, done, len(coros))

    job.progress(stage, 0, len(coros))
    await asyncio.gather(*(one(i, c) for i, c in enumerate(coros)))
    return results, errors


async def generate_set(job: Job, set_id: str, project_id: str, version: dict[str, Any], size: int) -> dict[str, Any]:
    try:
        return await _generate_set(job, set_id, project_id, version, size)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE eval_sets SET status='failed', error=? WHERE id=?",
                            (vault.redact(str(e)), set_id))
        raise


async def _generate_set(job: Job, set_id: str, project_id: str, version: dict[str, Any], size: int) -> dict[str, Any]:
    cfg = sync.version_config(version)
    build = await ready_build(project_id, cfg, job)
    chunks = await db.fetch_all(
        "SELECT c.id, c.document_id, c.ordinal, c.text, c.token_count, c.is_table, c.heading_path,"
        " d.filename AS document FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.build_id=?",
        (build["id"],))
    sample = M.sample_chunks(chunks, math.ceil(size * 1.5))
    if not sample:
        raise EvalError("No chunks are long enough to write questions from. Add more documents.")
    provider, opts = llm_settings(cfg)

    batches = [sample[i:i + GEN_BATCH] for i in range(0, len(sample), GEN_BATCH)]
    gen, errors = await gather_tolerant([_generate_batch(provider, opts, b) for b in batches], job, "generate")
    candidates = [c for batch in gen if batch for c in batch]
    if not candidates:
        raise EvalError(str(errors[0]) if errors else "The model returned no usable questions.")

    seen: set[str] = set()
    unique = []
    for c in candidates:
        key = M.normalize(c["question"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    vbatches = [unique[i:i + VAL_BATCH] for i in range(0, len(unique), VAL_BATCH)]
    closed, _ = await gather_tolerant(
        [_closed_book(provider, opts, [c["question"] for c in b]) for b in vbatches], job, "validate")

    rows = []
    stats = {"sampled": len(sample), "generated": len(unique), "kept": 0,
             "too_generic": 0, "bad_evidence": 0, "other": 0}
    for bi, batch in enumerate(vbatches):
        answers = closed[bi] or {}
        for j, cand in enumerate(batch):
            cb = answers.get(j)
            reason = check_candidate(cand, cb)
            valid = reason is None and stats["kept"] < size
            if valid:
                stats["kept"] += 1
            elif reason is None:
                continue  # over the requested size
            elif reason.startswith("too generic"):
                stats["too_generic"] += 1
            elif reason.startswith("evidence"):
                stats["bad_evidence"] += 1
            else:
                stats["other"] += 1
            rows.append((db.new_id(), set_id, len(rows), cand["question"], cand["answer"], cand["evidence"],
                         cand["chunk"]["document_id"], cand["chunk"]["id"], int(valid), reason, cb,
                         db.dumps(cand.get("facets") or [])))

    fingerprint = await corpus_sha(project_id)
    async with db.tx() as c:
        await c.executemany(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id, valid, reject_reason, closed_book_answer, facets) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
        await c.execute("UPDATE eval_sets SET status='ready', stats=?, build_id=?, corpus_sha=? WHERE id=?",
                        (db.dumps(stats), build["id"], fingerprint, set_id))
    return {"eval_set_id": set_id, **stats}


# --- hand-edited items ---------------------------------------------------------

MANUAL_COVERAGE = 0.9  # same bar as generated evidence (check_candidate)


async def check_evidence(build_id: str | None, document_id: str, evidence: str) -> str | None:
    """Reason a hand-written item can't be scored, or None. The evidence must be (nearly)
    verbatim in one of the document's chunks, or the hit rule can never fire."""
    if len(M.tokens(evidence)) < M.MIN_EVIDENCE_TOKENS:
        return f"Evidence needs at least {M.MIN_EVIDENCE_TOKENS} words copied from the document."
    if build_id is None:
        return None  # nothing indexed to check against (shouldn't happen for a ready set)
    chunks = await db.fetch_all("SELECT text FROM chunks WHERE build_id=? AND document_id=?", (build_id, document_id))
    if not chunks:
        return "That document isn't in this eval set's index. Rebuild the index or regenerate the set."
    if not any(M.coverage(evidence, c["text"]) >= MANUAL_COVERAGE for c in chunks):
        return "The evidence wasn't found in that document. Copy a sentence from it word for word."
    return None


# --- scoring ------------------------------------------------------------------

def final_k(cfg: dict[str, Any]) -> int:
    top_k = int(cfg["retrieve"].get("top_k", 8))
    if cfg["rerank"]["type"] != "none":
        return min(top_k, int(cfg["rerank"].get("top_n", 5)))
    return top_k


def config_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    ch, emb, rr = cfg["chunk"], cfg["embed"], cfg["rerank"]
    return {
        "parse": cfg["parse"]["type"],
        "chunk": f"{ch['type']} {ch.get('size', '')}{' ' + ch['unit'] if ch.get('unit') else ''}".strip(),
        "embed": emb.get("model") or emb["type"],
        "store": cfg["vector_store"]["type"],
        "dense": dense_used(cfg),
        "retrieve": cfg["retrieve"]["type"],
        "top_k": cfg["retrieve"].get("top_k"),
        "rerank": rr["type"] if rr["type"] == "none" else f"{rr['type']} top {rr.get('top_n')}",
    }


FIX_LIMITS = {"top_k": 50, "top_n": 50, "max_context_tokens": 100000}


def suggest_fix(cfg: dict[str, Any], diagnosis: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one-setting change that addresses a miss diagnosis (PRD FR-2.13), as a full new
    config; None when no single setting fixes it (not_retrieved, failed_to_extract)."""
    hits = [r for r in results if r.get("diagnosis") == diagnosis]
    if not hits:
        return None
    new = copy.deepcopy(cfg)
    rt, rr, pr = new["retrieve"], new["rerank"], new["prompt"]
    if diagnosis == "ranked_below_k":
        need = max(r["deep_rank"] or 0 for r in hits)
        rt["top_k"] = min(FIX_LIMITS["top_k"], max(int(rt["top_k"]) + 1, need))
        rt["candidates"] = max(int(rt.get("candidates", 40)), rt["top_k"])
    elif diagnosis == "dropped_by_rerank" and rr["type"] != "none":
        rr["top_n"] = min(FIX_LIMITS["top_n"], int(rt["top_k"]), int(rr["top_n"]) + 3)
    elif diagnosis == "dropped_by_budget":
        cur = int(pr["max_context_tokens"])
        pr["max_context_tokens"] = min(FIX_LIMITS["max_context_tokens"], -(-cur * 3 // 2 // 500) * 500)
    else:
        return None
    return new if new != cfg else None


def deep_config(cfg: dict[str, Any]) -> dict[str, Any]:
    deep = copy.deepcopy(cfg)
    deep["retrieve"]["top_k"] = DEEP_K
    deep["retrieve"]["candidates"] = max(int(deep["retrieve"].get("candidates", 40)), DEEP_K)
    deep["retrieve"]["mmr"] = False
    return deep


# Answer-level modes (need answer grading), tried in this order once the evidence reached the prompt.
ANSWER_DIAGNOSES = ("incorrect_format", "incomplete_answer", "wrong_specificity", "failed_to_extract")
DIAGNOSES = (*ANSWER_DIAGNOSES, "dropped_by_budget", "dropped_by_rerank", "ranked_below_k", "not_retrieved")


async def score_item(build: dict[str, Any], cfg: dict[str, Any], deep: dict[str, Any],
                     item: dict[str, Any]) -> dict[str, Any]:
    q = item["question"]
    ctx = RunContext()
    t0 = time.perf_counter()
    retrieved = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=q)
    final = await retrieval.rerank(ctx, cfg, q, retrieved)
    # A cached LLM step (query expansion, agent run) took ~0 ms here; count the time it really takes,
    # as cost and tokens already are, so cells that share the cache aren't scored as faster.
    ms = (time.perf_counter() - t0) * 1000 + sum(e.payload.get("uncached_ms", 0.0) for e in ctx.events)
    rank = M.first_hit_rank(final, item)
    # What the prompt packer would actually send: the cost of a query, and whether
    # the evidence survives the context budget (PRD "context inclusion").
    included, _ = build_node("prompt", cfg["prompt"]).pack(final)
    in_context = any(M.is_hit(r, item) for r in included)
    diagnosis = None
    deep_rank = None
    if rank is not None and not in_context:
        diagnosis = "dropped_by_budget"
    elif rank is None:
        if M.first_hit_rank(retrieved, item) is not None:
            diagnosis = "dropped_by_rerank"
        else:
            deep_hits = await retrieval.retrieve(RunContext(), build=build, cfg=deep, question=q)
            deep_rank = M.first_hit_rank(deep_hits, item)
            diagnosis = "ranked_below_k" if deep_rank else "not_retrieved"
    return {
        "item_id": item["id"],
        "rank": rank,
        "hit": rank is not None,
        "diagnosis": diagnosis,
        "deep_rank": deep_rank,
        "in_context": in_context,
        "ctx_tokens": sum(approx_tokens(packed_text(r)) for r in included),
        "llm_tokens": query_tokens(ctx.events),
        "cost_usd": query_cost(ctx.events),
        "ms": round(ms, 1),
        "top": [{"id": r["id"], "document": r["document"], "heading_path": r["heading_path"],
                 "hit": M.is_hit(r, item)} for r in final[:5]],
        "_final": final,  # popped by score_config; only answer grading needs it
    }


async def run_eval(job: Job, run_id: str, project_id: str, set_id: str, version: dict[str, Any],
                   answers: bool = False, judge: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        return await _run_eval(job, run_id, project_id, set_id, version, answers, judge)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE eval_runs SET status='failed', error=? WHERE id=?",
                            (vault.redact(str(e)), run_id))
        raise


async def _run_eval(job: Job, run_id: str, project_id: str, set_id: str, version: dict[str, Any],
                    answers: bool = False, judge: dict[str, str] | None = None) -> dict[str, Any]:
    row = await db.fetch_one("SELECT revision FROM eval_sets WHERE id=?", (set_id,))
    items = await valid_items(set_id)
    build, metrics, results = await score_config(job, project_id, sync.version_config(version), items,
                                                 answers=answers, judge=judge)
    async with db.tx() as c:
        await c.execute("UPDATE eval_runs SET status='ready', metrics=?, results=?, build_id=?, set_revision=?"
                        " WHERE id=?", (db.dumps(metrics), db.dumps(results), build["id"],
                                        row["revision"] if row else None, run_id))
    return {"eval_run_id": run_id, **{k_: metrics[k_] for k_ in ("hit_at_1", "hit_at_k", "mrr")}}


async def valid_items(set_id: str) -> list[dict[str, Any]]:
    items = await db.fetch_all(
        "SELECT * FROM eval_items WHERE eval_set_id=? AND valid=1 ORDER BY ordinal", (set_id,))
    if not items:
        raise EvalError("This eval set has no valid questions.")
    return items


async def score_config(job: Job, project_id: str, cfg: dict[str, Any], items: list[dict[str, Any]],
                       stage: str | None = "evaluate", answers: bool = False,
                       judge: dict[str, str] | None = None, judged: list[dict[str, Any]] | None = None,
                       ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Score one pipeline config against eval items -> (build, metrics, per-item results).
    `answers=True` also generates each answer and has an LLM grade it (costs LLM calls); the grader
    is `judge` = {provider, model}, default the version's own model. `judged`, if given, receives
    the grader's inputs so a caller can re-judge them (sweep median-of-3). A config with an `external`
    key is a RAG system running elsewhere (PRD §8.7): scored by calling it, with no build."""
    if "external" in cfg:
        return await score_external(job, project_id, cfg, items, stage, answers, judge, judged)
    build = await ready_build(project_id, cfg, job)
    deep = deep_config(cfg)
    results = []
    if stage:
        job.progress(stage, 0, len(items))
    for i, item in enumerate(items, start=1):
        results.append(await score_item(build, cfg, deep, item))
        if stage:
            job.progress(stage, i, len(items))
    finals = [r.pop("_final") for r in results]

    metrics = M.summarize([r["rank"] for r in results], final_k(cfg))
    metrics["p50_ms"] = round(M.percentile([r["ms"] for r in results], 0.5), 1)
    metrics["p95_ms"] = round(M.percentile([r["ms"] for r in results], 0.95), 1)
    metrics["context_hit"] = round(sum(r["in_context"] for r in results) / len(results), 4) if results else 0.0
    metrics["ctx_tokens"] = round(sum(r["ctx_tokens"] for r in results) / len(results)) if results else 0
    # The cost axis: what a query sends to LLMs — the answer prompt's context plus retrieval-side calls
    # (expansion, agent planning). Equals ctx_tokens when retrieval makes no LLM calls.
    metrics["query_tokens"] = (round(sum(r["ctx_tokens"] + r["llm_tokens"] for r in results) / len(results))
                               if results else 0)
    metrics["cost_per_1k"] = M.per_1k([r["cost_usd"] for r in results])  # retrieval stage: query expansion
    metrics["index"] = await stores.index_size(build)
    if answers:
        todo, label = await grade_answers(job, cfg, items, results, finals, judge, build)
        metrics["answers"] = {**M.answer_summary(results), "judge": label}
        if judged is not None:
            judged.extend(todo)
    metrics["diagnoses"] = {d: sum(1 for r in results if r["diagnosis"] == d) for d in DIAGNOSES}
    metrics["config"] = config_summary(cfg)
    return build, metrics, results


async def score_item_external(ext: external.ExternalConfig, item: dict[str, Any]) -> dict[str, Any]:
    """Score one question against an external system. Only what's observable from outside: the rank of the
    evidence in the contexts it returned (`not_retrieved` if absent); the rerank/budget modes need our internals."""
    try:
        got = await external.query(ext, item["question"])
    except external.ExternalError as e:
        return {"item_id": item["id"], "rank": None, "hit": False, "diagnosis": None, "deep_rank": None,
                "in_context": False, "ctx_tokens": 0, "llm_tokens": 0, "cost_usd": None, "ms": 0.0, "top": [],
                "error": vault.redact(str(e)), "_final": [], "_answer": None}
    final = got["contexts"]
    rank = M.first_hit_rank(final, item)
    return {
        "item_id": item["id"], "rank": rank, "hit": rank is not None,
        "diagnosis": None if rank else "not_retrieved", "deep_rank": None, "in_context": rank is not None,
        "ctx_tokens": sum(approx_tokens(c["text"]) for c in final), "llm_tokens": 0,
        "cost_usd": None,  # the external system's own cost is unknown to us
        "ms": round(got["ms"], 1),
        "top": [{"id": str(i), "document": c["external_source"], "heading_path": "", "hit": M.is_hit(c, item)}
                for i, c in enumerate(final[:5], start=1)],
        "_final": final, "_answer": got["answer"],
    }


async def score_external(job: Job, project_id: str, cfg: dict[str, Any], items: list[dict[str, Any]],
                         stage: str | None, answers: bool, judge: dict[str, str] | None,
                         judged: list[dict[str, Any]] | None,
                         ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    ext = external.ExternalConfig(**cfg["external"])
    if answers and not judge:
        raise EvalError("Pick a judge model to grade an external system's answers.")
    names = {d["id"]: d["filename"] for d in await db.fetch_all(
        "SELECT id, filename FROM documents WHERE project_id=?", (project_id,))}
    if stage:
        job.progress(stage, 0, len(items))
    results = []
    for i, item in enumerate(items, start=1):  # one at a time, like a native run, so latency is honest
        results.append(await score_item_external(ext, {**item, "filename": names.get(item["document_id"])}))
        if stage:
            job.progress(stage, i, len(items))
    failed = [r for r in results if r.get("error")]
    if len(failed) == len(results):
        raise EvalError(failed[0]["error"])
    finals = [r.pop("_final") for r in results]
    sent = [r.pop("_answer") for r in results]

    metrics = M.summarize([r["rank"] for r in results], ext.top_k)
    metrics["p50_ms"] = round(M.percentile([r["ms"] for r in results if not r.get("error")], 0.5), 1)
    metrics["p95_ms"] = round(M.percentile([r["ms"] for r in results if not r.get("error")], 0.95), 1)
    metrics["context_hit"] = round(sum(r["in_context"] for r in results) / len(results), 4)
    metrics["ctx_tokens"] = metrics["query_tokens"] = round(sum(r["ctx_tokens"] for r in results) / len(results))
    metrics["cost_per_1k"] = None
    metrics["errors"] = len(failed)
    if answers:
        if not any(sent):
            raise EvalError("The system returned no answers to grade (retrieval-only?). Turn off answer grading.")
        answered = [{"answer": a, "sources": [c["text"][:GRADE_CONTEXT_CHARS] for c in f], "cost_usd": None,
                     "ms": r["ms"]} if a is not None else None for a, f, r in zip(sent, finals, results)]
        todo, label = await grade_answers(job, cfg, items, results, finals, judge, answered=answered)
        metrics["answers"] = {**M.answer_summary(results), "judge": label}
        if judged is not None:
            judged.extend(todo)
    metrics["diagnoses"] = {d: sum(1 for r in results if r["diagnosis"] == d) for d in DIAGNOSES}
    metrics["config"] = {"external": vault.redact_url(ext.url)}
    return {"id": None}, metrics, results


# --- answer grading (LLM) ---------------------------------------------------------

async def generate_answer(cfg: dict[str, Any], question: str, final: list[dict[str, Any]],
                          build: dict[str, Any] | None = None, tests: str | None = None) -> dict[str, Any]:
    """Answer exactly as the chat path would (same packer, prompt and model), without streaming —
    including the Verify slot: a grounding check, and its retries with more context (which need
    `build` to retrieve again). `ms` = answer latency: generation + checks + retries."""
    gen = build_node("generate", cfg["generate"])
    verifier = build_node("verify", cfg.get("verify") or {"type": "none"})
    checking = isinstance(verifier, verify_node.GroundingCheck)
    retries = (verifier.config.max_retries if checking and build is not None
               and verifier.config.on_fail == "retry_with_more_context" else 0)
    t0 = time.perf_counter()
    cost: float | None = 0.0
    attempt_cfg, verification = cfg, None
    for attempt in range(retries + 1):
        if attempt:
            attempt_cfg = verify_node.more_context(attempt_cfg)
            ctx = RunContext()
            final = await retrieval.rerank(ctx, attempt_cfg, question, await retrieval.retrieve(
                ctx, build=build, cfg=attempt_cfg, question=question))
            cost = add_cost(cost, query_cost(ctx.events))
        built = build_node("prompt", attempt_cfg["prompt"]).build(question, final)
        usage: dict[str, Any] = {}

        async def answer() -> str:
            usage.clear()
            return "".join([d async for d in gen.stream(built["messages"], usage)])

        async with _llm_slots:
            text = await llm.retrying(answer)
        cost = add_cost(cost, llm.cost_usd(gen.provider, gen.model_name, usage.get("tokens_in", 0),
                                           usage.get("tokens_out", 0)))
        if not checking:
            break
        async with _llm_slots:
            v = await verifier.check(gen, question, text, built["included"])
        cost = add_cost(cost, v.pop("cost_usd") if v["status"] == "ok" else 0.0)
        verification = {"status": v["status"], "grounded": v["grounded"], "score": v["score"],
                        "attempt": attempt, "claims": len(v["claims"])}
        if v["grounded"] is not False:
            break
    # FR-3.17: a question with tests gets its answer's code executed against them whatever the config —
    # with the code check on, the model may fix failures; otherwise it's one honest run.
    execution = None
    exec_check = isinstance(verifier, verify_node.ExecutionCheck)
    if exec_check or (tests and codecheck.extract_code(text)):
        c = verifier.config if exec_check else None
        res = await codecheck.check(gen, question, text, [x["text"] for x in built["included"]], tests=tests,
                                    max_steps=c.max_steps if c else 1, allow_generated=bool(c and c.allow_generated_tests),
                                    timeout_s=c.timeout_s if c else 10)
        cost = add_cost(cost, llm.cost_usd(gen.provider, gen.model_name, res["tokens_in"], res["tokens_out"])
                        if res["tokens_in"] or res["tokens_out"] else 0.0)
        text = res["answer"]
        execution = {k: res.get(k) for k in ("status", "test_source", "attempts", "error")}
    if verify_node.output_validation(cfg):
        text, _ = verify_node.filter_unsourced(text, [c["text"] for c in built["included"]])
    return {"answer": text.strip(), "sources": [c["text"][:GRADE_CONTEXT_CHARS] for c in built["included"]],
            "cost_usd": cost, "ms": round((time.perf_counter() - t0) * 1000, 1), "verification": verification,
            "execution": execution}


def query_tokens(events: list[TraceEvent]) -> int:
    """LLM tokens (in + out) one retrieval spent — query expansion, agent planning — counting a
    cached call at what it cost, like `query_cost`."""
    return sum(e.payload.get("uncached_tokens", e.tokens_in + e.tokens_out) for e in events)


def query_cost(events: list[TraceEvent]) -> float | None:
    """List-price LLM cost of one retrieval (query expansion), counting a cached expansion at what
    the call cost; None if any call's model has no known price."""
    total = 0.0
    for e in events:
        if e.payload.get("priced") is False:
            return None
        c = e.payload["uncached_cost_usd"] if "uncached_cost_usd" in e.payload else e.cost_usd
        if c is None:
            return None
        total += c
    return total


def add_cost(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def judge_settings(cfg: dict[str, Any], judge: dict[str, str] | None) -> tuple[str, dict[str, Any], str]:
    """(provider, opts, label) for the answer grader: `judge` if given, else the version's own
    Generate model. Always temperature 0: Gemini and NVIDIA accept it, and it lowers judge variance."""
    if judge:
        provider, opts = judge["provider"], {"model": judge.get("model") or ""}
    else:
        provider, opts = llm_settings(cfg)
    return provider, {**opts, "temperature": 0}, f"{provider}/{opts['model'] or 'default model'}"


async def _grade_batch(provider: str, opts: dict[str, Any], batch: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    parts = []
    for i, b in enumerate(batch, start=1):
        sources = "\n".join(f"  [{k}] {t}" for k, t in enumerate(b["sources"], start=1)) or "  (none)"
        facts = "".join(f"\n  {k}. {f}" for k, f in enumerate(b["facets"], start=1))
        parts.append(f"### Item {i}\nQuestion: {b['question']}\nReference answer: {b['gold']}\n"
                     + (f"Required facts:{facts}\n" if facts else "")
                     + f"System answer: {b['answer'] or '(empty)'}\nSources:\n{sources}")
    raw = await complete(provider, opts, GRADE_SYSTEM, "\n\n".join(parts))
    out: dict[int, dict[str, Any]] = {}
    for r in (parse_json(raw) or {}).get("results", []):
        try:
            idx = int(r.get("id")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < len(batch):
            continue
        g = {k: str(r.get(k) or "").lower() for k in ("correct", "grounded", "relevant", "specificity")}
        if g["correct"] not in LEVELS:
            continue
        out[idx] = {"correct": g["correct"],
                    **{k: g[k] if g[k] in LEVELS else None for k in ("grounded", "relevant")},
                    "specificity": g["specificity"] if g["specificity"] in SPECIFICITY else None}
        facets, facts = batch[idx]["facets"], r.get("facts")
        if facets and isinstance(facts, list) and len(facts) == len(facets):
            out[idx]["missing_facts"] = [f for f, v in zip(facets, facts) if str(v).lower() != "yes"]
        out[idx].update(contextual(r, len(batch[idx]["sources"]), len(facets) or 1))
    return out


def contextual(r: dict[str, Any], n_sources: int, n_facts: int) -> dict[str, float | None]:
    """Contextual precision/recall from the judge's per-source and per-fact yes/no lists.
    No sources -> both 0; a list of the wrong length -> None (not scored)."""
    if n_sources == 0:
        return {"context_precision": 0.0, "context_recall": 0.0}

    def flags(key: str, n: int) -> list[bool] | None:
        v = r.get(key)
        return [str(x).lower() == "yes" for x in v] if isinstance(v, list) and len(v) == n else None

    rel, sup = flags("sources_relevant", n_sources), flags("facts_in_sources", n_facts)
    return {"context_precision": M.context_precision(rel) if rel is not None else None,
            "context_recall": round(sum(sup) / n_facts, 4) if sup is not None else None}


def format_problem(answer: str, n_sources: int) -> str | None:
    """Mode 5: the answer breaks the prompt's citation contract — no [n] markers, or numbers
    outside the sources it was given. A plain "I don't know" needs no citation."""
    if n_sources == 0:
        return None
    nums = [int(x) for m in chat._CITE.finditer(answer) for x in re.split(r"\s*[,;]\s*", m.group(1))]
    if not nums:
        return None if _REFUSAL.search(answer) else "no [n] citations"
    bad = sorted({n for n in nums if not 1 <= n <= n_sources})
    if bad:
        return f"cites [{bad[0]}] but only {n_sources} source(s) were given"
    return None


_REFUSAL = re.compile(r"\b(don't|do not|doesn't|does not|cannot|can't|unable to)\b.{0,20}\b(know|contain|say|mention"
                      r"|provide|find|answer)", re.I)


def asks_for_citations(cfg: dict[str, Any]) -> bool:
    p = cfg["prompt"]
    return p["type"] != "custom" or bool(re.search(r"\[1\]|\bcit", p.get("system_prompt", ""), re.I))


def diagnose_answer(r: dict[str, Any]) -> None:
    """FR-2.11: one diagnosis per failed question, most upstream first. Retrieval modes (2, 3) are
    already set; for a wrong/partial answer whose evidence reached the prompt: format (5) →
    missing facts (7) → judged specificity (6) → otherwise failed to extract (4)."""
    if r.get("diagnosis") in ANSWER_DIAGNOSES:
        r["diagnosis"] = None
    if r.get("diagnosis") or not r.get("in_context") or r.get("correct") not in ("no", "partial"):
        return
    if r.get("format_error"):
        r["diagnosis"] = "incorrect_format"
    elif r.get("missing_facts"):
        r["diagnosis"] = "incomplete_answer"
    elif r.get("specificity") in ("too_vague", "too_verbose"):
        r["diagnosis"] = "wrong_specificity"
    else:
        r["diagnosis"] = "failed_to_extract"


async def _judge(job: Job, provider: str, opts: dict[str, Any], todo: list[dict[str, Any]],
                 stage: str = "grade") -> dict[int, dict[str, Any]]:
    """Grade every todo entry -> {result index: verdicts}; a failed batch leaves its entries out.
    Raises EvalError when there was something to grade and nothing got a verdict."""
    batches = [todo[i:i + GRADE_BATCH] for i in range(0, len(todo), GRADE_BATCH)]
    graded, errors = await gather_tolerant([_grade_batch(provider, opts, b) for b in batches], job, stage)
    out = {t["i"]: g for b, res in zip(batches, graded) for j, t in enumerate(b) if (g := (res or {}).get(j))}
    if todo and not out:
        raise EvalError(f"Answer grading failed: {errors[0] if errors else 'the judge returned no verdicts'}")
    return out


async def grade_answers(job: Job, cfg: dict[str, Any], items: list[dict[str, Any]],
                        results: list[dict[str, Any]], finals: list[list[dict[str, Any]]],
                        judge: dict[str, str] | None = None, build: dict[str, Any] | None = None,
                        answered: list[dict[str, Any] | None] | None = None,
                        ) -> tuple[list[dict[str, Any]], str]:
    """Fill results[i] with answer + verdicts, then diagnose the in-context failures (modes 4–7).
    `answered` = answers already produced elsewhere (an external system); else they're generated here.
    Returns (the grader's inputs, judge label)."""
    errors: list[Any] = []
    if answered is None:
        answered, errors = await gather_tolerant(
            [generate_answer(cfg, it["question"], f, build, it.get("tests")) for it, f in zip(items, finals)], job, "answer")
    cites = "external" not in cfg and asks_for_citations(cfg)
    todo = [{"i": i, "question": it["question"], "gold": it["gold_answer"],
             "facets": db.loads(it.get("facets"), []) or [], **a}
            for i, (it, a) in enumerate(zip(items, answered)) if a]
    if items and not todo:
        raise EvalError(f"Answer generation failed: {errors[0] if errors else 'no answers'}")
    for t in todo:
        r = results[t["i"]]
        r["answer"] = t["answer"]
        if t.get("ms") is not None:
            r["answer_ms"] = t["ms"]
        if t.get("verification"):
            r["verification"] = t["verification"]
        if t.get("execution"):
            r["execution"] = {**t["execution"], "has_tests": bool(items[t["i"]].get("tests"))}
        r["cost_usd"] = add_cost(r.get("cost_usd"), t.get("cost_usd"))
        if cites and (problem := format_problem(t["answer"], len(t["sources"]))):
            r["format_error"] = problem
    provider, opts, label = judge_settings(cfg, judge)
    for i, g in (await _judge(job, provider, opts, todo)).items():
        results[i].update(g)
        diagnose_answer(results[i])
    return todo, label


def median_verdict(votes: list[str | None]) -> str | None:
    """Median of yes > partial > no verdicts (an even count takes the lower one); None if no votes."""
    v = sorted((x for x in votes if x in LEVELS), key=LEVELS.index)
    return v[len(v) // 2] if v else None


async def rejudge(job: Job, cfg: dict[str, Any], judge: dict[str, str] | None, todo: list[dict[str, Any]],
                  results: list[dict[str, Any]], times: int = 2) -> None:
    """FR-2.8: grade the same answers `times` more and keep each question's median verdict."""
    provider, opts, _ = judge_settings(cfg, judge)
    extra = [await _judge(job, provider, opts, todo, "rejudge") for _ in range(times)]
    for t in todo:
        r = results[t["i"]]
        if not r.get("correct"):
            continue
        for key in ("correct", "grounded", "relevant"):
            votes = [r.get(key), *(e.get(t["i"], {}).get(key) for e in extra)]
            if all(v in LEVELS for v in votes):  # a missing extra vote keeps the original verdict
                r[key] = median_verdict(votes)
        diagnose_answer(r)
