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
from ..core.node import RunContext
from ..core.pipeline import index_config_hash
from ..ingest.jobs import Job
from ..llm import provider as llm
from . import chat, retrieval, sync

GEN_BATCH = 5
VAL_BATCH = 10
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


async def _gather_tolerant(coros: list, job: Job, stage: str) -> tuple[list[Any], list[Exception]]:
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
    gen, errors = await _gather_tolerant([_generate_batch(provider, opts, b) for b in batches], job, "generate")
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
    closed, _ = await _gather_tolerant(
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


def deep_config(cfg: dict[str, Any]) -> dict[str, Any]:
    deep = copy.deepcopy(cfg)
    deep["retrieve"]["top_k"] = DEEP_K
    deep["retrieve"]["candidates"] = max(int(deep["retrieve"].get("candidates", 40)), DEEP_K)
    deep["retrieve"]["mmr"] = False
    return deep


async def score_item(build: dict[str, Any], cfg: dict[str, Any], deep: dict[str, Any],
                     item: dict[str, Any]) -> dict[str, Any]:
    q = item["question"]
    ctx = RunContext()
    t0 = time.perf_counter()
    retrieved = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=q)
    final = await retrieval.rerank(ctx, cfg, q, retrieved)
    ms = (time.perf_counter() - t0) * 1000
    rank = M.first_hit_rank(final, item)
    diagnosis = None
    deep_rank = None
    if rank is None:
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
        "ms": round(ms, 1),
        "top": [{"id": r["id"], "document": r["document"], "heading_path": r["heading_path"],
                 "hit": M.is_hit(r, item)} for r in final[:5]],
    }


async def run_eval(job: Job, run_id: str, project_id: str, set_id: str, version: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _run_eval(job, run_id, project_id, set_id, version)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE eval_runs SET status='failed', error=? WHERE id=?", (str(e), run_id))
        raise


async def _run_eval(job: Job, run_id: str, project_id: str, set_id: str, version: dict[str, Any]) -> dict[str, Any]:
    cfg = sync.version_config(version)
    build = await ready_build(project_id, cfg, job)
    items = await db.fetch_all(
        "SELECT * FROM eval_items WHERE eval_set_id=? AND valid=1 ORDER BY ordinal", (set_id,))
    if not items:
        raise EvalError("This eval set has no valid questions.")
    deep = deep_config(cfg)
    results = []
    job.progress("evaluate", 0, len(items))
    for i, item in enumerate(items, start=1):
        results.append(await score_item(build, cfg, deep, item))
        job.progress("evaluate", i, len(items))

    k = final_k(cfg)
    metrics = M.summarize([r["rank"] for r in results], k)
    metrics["p50_ms"] = round(M.percentile([r["ms"] for r in results], 0.5), 1)
    metrics["diagnoses"] = {d: sum(1 for r in results if r["diagnosis"] == d)
                            for d in ("dropped_by_rerank", "ranked_below_k", "not_retrieved")}
    metrics["config"] = config_summary(cfg)
    async with db.tx() as c:
        await c.execute("UPDATE eval_runs SET status='ready', metrics=?, results=?, build_id=? WHERE id=?",
                        (db.dumps(metrics), db.dumps(results), build["id"], run_id))
    return {"eval_run_id": run_id, **{k_: metrics[k_] for k_ in ("hit_at_1", "hit_at_k", "mrr")}}
