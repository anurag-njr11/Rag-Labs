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

from .. import db
from ..core import evalmetrics as M
from ..core.node import RunContext, build_node
from ..core.pipeline import index_config_hash
from ..ingest.jobs import Job
from ..llm import provider as llm
from ..nodes.chunk import approx_tokens
from . import chat, retrieval, sync

GEN_BATCH = 5
VAL_BATCH = 10
GRADE_BATCH = 5
GRADE_CONTEXT_CHARS = 800
GENERIC_F1 = 0.6
DEEP_K = 50
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
- If a passage has no answerable factual content (navigation, table of contents, boilerplate), use an empty question.
Reply with JSON only: {"items": [{"passage": 1, "question": "...", "answer": "...", "evidence": "..."}]}"""

VAL_SYSTEM = """Answer each question from your own general knowledge in at most 25 words.
You have no documents. If you do not know, answer "unknown".
Reply with JSON only: {"answers": [{"id": 1, "answer": "..."}]}"""


GRADE_SYSTEM = """You grade answers from a document question-answering system.
Each numbered item has the question, the reference answer, the system's answer, and the sources the system was given.
- "correct": "yes" if the system's answer states the reference answer's facts (wording may differ);
  "partial" if some facts are missing or vague; "no" if wrong, missing, or it says it doesn't know.
- "grounded": "yes" if every claim in the system's answer is supported by its sources;
  "partial" if some claims are not; "no" if it is mostly unsupported.
Reply with JSON only: {"results": [{"id": 1, "correct": "yes", "grounded": "yes"}]}"""
LEVELS = ("yes", "partial", "no")


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
    opts = dict(opts)
    if not opts["model"]:
        opts["model"] = await llm.resolve_model(provider, "chat")
    async with _llm_slots:
        try:
            resp = await llm.client(provider).chat.completions.create(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.3, max_tokens=4096, stream=False, **opts)
        except Exception as e:
            raise llm.friendly_error(provider, e) from e
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
                    "evidence": str(entry.get("evidence") or "").strip()})
    return out


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
            await c.execute("UPDATE eval_sets SET status='failed', error=? WHERE id=?", (str(e), set_id))
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
                         cand["chunk"]["document_id"], cand["chunk"]["id"], int(valid), reason, cb))

    async with db.tx() as c:
        await c.executemany(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id, valid, reject_reason, closed_book_answer) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        await c.execute("UPDATE eval_sets SET status='ready', stats=?, build_id=? WHERE id=?",
                        (db.dumps(stats), build["id"], set_id))
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


DIAGNOSES = ("failed_to_extract", "dropped_by_budget", "dropped_by_rerank", "ranked_below_k", "not_retrieved")


async def score_item(build: dict[str, Any], cfg: dict[str, Any], deep: dict[str, Any],
                     item: dict[str, Any]) -> dict[str, Any]:
    q = item["question"]
    ctx = RunContext()
    t0 = time.perf_counter()
    retrieved = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=q)
    final = await retrieval.rerank(ctx, cfg, q, retrieved)
    ms = (time.perf_counter() - t0) * 1000
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
        "ctx_tokens": sum(approx_tokens(r["text"]) for r in included),
        "ms": round(ms, 1),
        "top": [{"id": r["id"], "document": r["document"], "heading_path": r["heading_path"],
                 "hit": M.is_hit(r, item)} for r in final[:5]],
        "_final": final,  # popped by score_config; only answer grading needs it
    }


async def run_eval(job: Job, run_id: str, project_id: str, set_id: str, version: dict[str, Any],
                   answers: bool = False) -> dict[str, Any]:
    try:
        return await _run_eval(job, run_id, project_id, set_id, version, answers)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE eval_runs SET status='failed', error=? WHERE id=?", (str(e), run_id))
        raise


async def _run_eval(job: Job, run_id: str, project_id: str, set_id: str, version: dict[str, Any],
                    answers: bool = False) -> dict[str, Any]:
    items = await valid_items(set_id)
    build, metrics, results = await score_config(job, project_id, sync.version_config(version), items,
                                                 answers=answers)
    async with db.tx() as c:
        await c.execute("UPDATE eval_runs SET status='ready', metrics=?, results=?, build_id=? WHERE id=?",
                        (db.dumps(metrics), db.dumps(results), build["id"], run_id))
    return {"eval_run_id": run_id, **{k_: metrics[k_] for k_ in ("hit_at_1", "hit_at_k", "mrr")}}


async def valid_items(set_id: str) -> list[dict[str, Any]]:
    items = await db.fetch_all(
        "SELECT * FROM eval_items WHERE eval_set_id=? AND valid=1 ORDER BY ordinal", (set_id,))
    if not items:
        raise EvalError("This eval set has no valid questions.")
    return items


async def score_config(job: Job, project_id: str, cfg: dict[str, Any], items: list[dict[str, Any]],
                       stage: str | None = "evaluate",
                       answers: bool = False) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Score one pipeline config against eval items -> (build, metrics, per-item results).
    `answers=True` also generates each answer and has the LLM grade it (costs LLM calls)."""
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
    metrics["context_hit"] = round(sum(r["in_context"] for r in results) / len(results), 4) if results else 0.0
    metrics["ctx_tokens"] = round(sum(r["ctx_tokens"] for r in results) / len(results)) if results else 0
    if answers:
        await grade_answers(job, cfg, items, results, finals)
        metrics["answers"] = M.answer_summary(results)
    metrics["diagnoses"] = {d: sum(1 for r in results if r["diagnosis"] == d) for d in DIAGNOSES}
    metrics["config"] = config_summary(cfg)
    return build, metrics, results


# --- answer grading (LLM) ---------------------------------------------------------

async def generate_answer(cfg: dict[str, Any], question: str, final: list[dict[str, Any]]) -> dict[str, Any]:
    """Answer exactly as the chat path would (same packer, prompt and model), without streaming."""
    built = build_node("prompt", cfg["prompt"]).build(question, final)
    gen = build_node("generate", cfg["generate"])
    async with _llm_slots:
        text = "".join([d async for d in gen.stream(built["messages"], {})])
    return {"answer": text.strip(), "sources": [c["text"][:GRADE_CONTEXT_CHARS] for c in built["included"]]}


async def _grade_batch(provider: str, opts: dict[str, Any], batch: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    parts = []
    for i, b in enumerate(batch, start=1):
        sources = "\n".join(f"  [{k}] {t}" for k, t in enumerate(b["sources"], start=1)) or "  (none)"
        parts.append(f"### Item {i}\nQuestion: {b['question']}\nReference answer: {b['gold']}\n"
                     f"System answer: {b['answer'] or '(empty)'}\nSources:\n{sources}")
    raw = await complete(provider, opts, GRADE_SYSTEM, "\n\n".join(parts))
    out: dict[int, dict[str, Any]] = {}
    for r in (parse_json(raw) or {}).get("results", []):
        try:
            idx = int(r.get("id")) - 1
        except (TypeError, ValueError):
            continue
        correct, grounded = str(r.get("correct") or "").lower(), str(r.get("grounded") or "").lower()
        if correct in LEVELS:
            out[idx] = {"correct": correct, "grounded": grounded if grounded in LEVELS else None}
    return out


async def grade_answers(job: Job, cfg: dict[str, Any], items: list[dict[str, Any]],
                        results: list[dict[str, Any]], finals: list[list[dict[str, Any]]]) -> None:
    """Fill results[i] with answer/correct/grounded. A wrong answer whose evidence was in
    context is diagnosed `failed_to_extract`: the passage was there, the model missed it."""
    answered, _ = await gather_tolerant(
        [generate_answer(cfg, it["question"], f) for it, f in zip(items, finals)], job, "answer")
    todo = [{"i": i, "question": it["question"], "gold": it["gold_answer"], **a}
            for i, (it, a) in enumerate(zip(items, answered)) if a]
    for t in todo:
        results[t["i"]]["answer"] = t["answer"]
    provider, opts = llm_settings(cfg)
    batches = [todo[i:i + GRADE_BATCH] for i in range(0, len(todo), GRADE_BATCH)]
    graded, _ = await gather_tolerant([_grade_batch(provider, opts, b) for b in batches], job, "grade")
    for b, res in zip(batches, graded):
        for j, t in enumerate(b):
            g = (res or {}).get(j)
            if not g:
                continue
            r = results[t["i"]]
            r.update(g)
            if g["correct"] == "no" and r["in_context"] and r["diagnosis"] is None:
                r["diagnosis"] = "failed_to_extract"
