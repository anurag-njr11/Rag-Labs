"""Corpus Health: what the documents can't answer, where they disagree, and what nobody uses.

One report = one background job over a version's build:
- coverage: real questions (Playground/API history + any the user pastes) are retrieved
  against the index; an LLM grades each as covered / partial / missing from the top
  passages (discrete verdicts, temperature 0.3, batched). Gaps are grouped into topics by
  greedy cosine clustering of the question embeddings -> a ranked content backlog.
- duplicates / contradictions: a blockwise cosine scan over the build's cached vectors
  finds cross-document pairs; near-identical pairs are duplicates (no LLM), close pairs
  get an LLM contradiction check.
- unused content: chunks and documents never retrieved by any analysed question.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from .. import db
from ..core import evalmetrics as M
from ..core.node import RunContext, build_node
from ..ingest.jobs import Job
from . import evaluate, retrieval, sync

JUDGE_BATCH = 5
PAIR_BATCH = 5
MAX_QUESTIONS = 200
PASSAGES_PER_QUESTION = 6  # roughly what the generator sees; fewer would flag answers sitting at rank 4+
PASSAGE_CHARS = 1200
CLUSTER_SIM = 0.75   # question-to-cluster cosine needed to join a gap topic
DUPLICATE_SIM = 0.97
NEAR_SIM = 0.85      # candidate pairs for the contradiction check
MAX_PAIRS = 30
VERDICTS = ("covered", "partial", "missing")

JUDGE_SYSTEM = """You check whether a documentation search result can answer user questions.
For each numbered question you get the top passages the search returned.
Verdict:
- "covered": the passages fully answer the question.
- "partial": they answer part of it, or only vaguely.
- "missing": they do not answer it.
For "partial" and "missing", "missing" names the documentation topic that would need to be added, as a noun
phrase of at most 8 words (e.g. "SSO configuration guide"). Never write the answer itself there.
Judge only from the passages, never from your own knowledge.
Reply with JSON only: {"results": [{"id": 1, "verdict": "covered", "missing": ""}]}"""

PAIR_SYSTEM = """You compare pairs of passages from different documents in one knowledge base.
For each numbered pair, decide whether they CONTRADICT each other: state different facts,
numbers, steps or rules about the same thing, so a reader could get opposite answers.
Merely different topics, or one passage being more detailed, is not a contradiction.
"explanation": one sentence naming the conflicting facts, or "" if none.
Reply with JSON only: {"results": [{"id": 1, "contradiction": false, "explanation": ""}]}"""


# --- pure helpers (unit-tested) -------------------------------------------------

def cluster(vectors: np.ndarray, threshold: float = CLUSTER_SIM) -> list[list[int]]:
    """Greedy single-pass clustering on cosine similarity, deterministic in input
    order: each item joins the most similar existing cluster centroid if that
    similarity >= threshold, else starts a new one. Largest clusters first."""
    # ponytail: O(n·clusters) greedy pass; fine for <= MAX_QUESTIONS, use HDBSCAN if questions reach thousands
    if len(vectors) == 0:
        return []
    v = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    groups: list[list[int]] = []
    sums: list[np.ndarray] = []
    for i, x in enumerate(v):
        if sums:
            cents = np.stack([s / np.linalg.norm(s) for s in sums])
            sims = cents @ x
            j = int(np.argmax(sims))
            if sims[j] >= threshold:
                groups[j].append(i)
                sums[j] = sums[j] + x
                continue
        groups.append([i])
        sums.append(x.copy())
    return sorted(groups, key=lambda g: (-len(g), g[0]))


def similar_pairs(vectors: np.ndarray, doc_ids: list[str], threshold: float,
                  limit: int, block: int = 512) -> list[tuple[int, int, float]]:
    """Cross-document pairs (i < j) with cosine >= threshold, most similar first.
    Blockwise so memory stays at block × n."""
    if len(vectors) < 2:
        return []
    v = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    docs = np.array(doc_ids)
    found: list[tuple[int, int, float]] = []
    for start in range(0, len(v), block):
        sims = v[start:start + block] @ v.T
        for r in range(sims.shape[0]):
            i = start + r
            row = sims[r]
            row[: i + 1] = -1  # only j > i
            row[docs == docs[i]] = -1  # other documents only
            for j in np.nonzero(row >= threshold)[0]:
                found.append((i, int(j), float(row[j])))
    found.sort(key=lambda p: (-p[2], p[0], p[1]))
    return found[:limit]


def coverage_summary(verdicts: list[str]) -> dict[str, Any]:
    n = len(verdicts)
    counts = {v: verdicts.count(v) for v in VERDICTS}
    return {"n": n, **counts, "covered_rate": round(counts["covered"] / n, 4) if n else 0.0}


# --- LLM steps --------------------------------------------------------------------

async def _judge(provider: str, opts: dict[str, Any], batch: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    parts = []
    for i, q in enumerate(batch, start=1):
        passages = "\n".join(f"  [{k}] {p['text'][:PASSAGE_CHARS]}" for k, p in enumerate(q["passages"], start=1))
        parts.append(f"### Question {i}: {q['question']}\nPassages:\n{passages or '  (none found)'}")
    raw = await evaluate.complete(provider, opts, JUDGE_SYSTEM, "\n\n".join(parts))
    out: dict[int, dict[str, str]] = {}
    for r in (evaluate.parse_json(raw) or {}).get("results", []):
        try:
            idx = int(r.get("id")) - 1
        except (TypeError, ValueError):
            continue
        verdict = str(r.get("verdict") or "").lower()
        if verdict in VERDICTS:
            out[idx] = {"verdict": verdict, "missing": str(r.get("missing") or "").strip()}
    return out


async def _check_pairs(provider: str, opts: dict[str, Any], batch: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    parts = [f"### Pair {i}\nA ({p['a']['document']}): {p['a']['text'][:PASSAGE_CHARS]}\n"
             f"B ({p['b']['document']}): {p['b']['text'][:PASSAGE_CHARS]}" for i, p in enumerate(batch, start=1)]
    raw = await evaluate.complete(provider, opts, PAIR_SYSTEM, "\n\n".join(parts))
    out: dict[int, dict[str, Any]] = {}
    for r in (evaluate.parse_json(raw) or {}).get("results", []):
        try:
            out[int(r.get("id")) - 1] = {"contradiction": bool(r.get("contradiction")),
                                         "explanation": str(r.get("explanation") or "").strip()}
        except (TypeError, ValueError):
            continue
    return out


# --- the report ----------------------------------------------------------------------

async def real_questions(project_id: str, extra: list[str]) -> list[dict[str, str]]:
    """Pasted questions first, then distinct Playground/API questions, newest first."""
    rows = await db.fetch_all("SELECT question FROM runs WHERE project_id=? AND kind='chat' AND question != ''"
                              " ORDER BY created_at DESC LIMIT 1000", (project_id,))
    seen: set[str] = set()
    out = []
    for source, qs in (("pasted", extra), ("history", [r["question"] for r in rows])):
        for q in qs:
            q = q.strip()
            key = M.normalize(q)
            if q and key and key not in seen:
                seen.add(key)
                out.append({"question": q, "source": source})
    return out[:MAX_QUESTIONS]


def _excerpt(c: dict[str, Any]) -> dict[str, Any]:
    return {"chunk_id": c["id"], "document_id": c["document_id"], "document": c["document"],
            "heading_path": c.get("heading_path") or "", "page_start": c.get("page_start"),
            "text": c["text"][:600]}


async def _coverage(job: Job, build: dict[str, Any], cfg: dict[str, Any],
                    questions: list[dict[str, str]]) -> tuple[dict[str, Any], set[str]]:
    used: set[str] = set()
    packer = build_node("prompt", cfg["prompt"])
    job.progress("retrieve", 0, len(questions))
    for i, q in enumerate(questions, start=1):
        ctx = RunContext()
        final = await retrieval.rerank(ctx, cfg, q["question"],
                                       await retrieval.retrieve(ctx, build=build, cfg=cfg, question=q["question"]))
        included, _ = packer.pack(final)
        used.update(c["id"] for c in included)
        q["passages"] = included[:PASSAGES_PER_QUESTION]
        job.progress("retrieve", i, len(questions))

    provider, opts = evaluate.llm_settings(cfg)
    batches = [questions[i:i + JUDGE_BATCH] for i in range(0, len(questions), JUDGE_BATCH)]
    judged, errors = await evaluate.gather_tolerant([_judge(provider, opts, b) for b in batches], job, "judge")
    if questions and not any(judged):
        raise evaluate.EvalError(str(errors[0]) if errors else "The model returned no verdicts.")
    for b, res in zip(batches, judged):
        for j, q in enumerate(b):
            v = (res or {}).get(j)
            q["verdict"] = v["verdict"] if v else None
            q["missing"] = v["missing"] if v else ""

    graded = [q for q in questions if q["verdict"]]
    gaps = [q for q in graded if q["verdict"] != "covered"]
    topics = []
    if gaps:
        embedder = build_node("embed", cfg["embed"])
        vecs = np.asarray(await embedder.embed_documents([q["question"] for q in gaps]), dtype=np.float32)
        for group in cluster(vecs):
            members = [gaps[i] for i in group]
            topics.append({
                # the first member's "missing" phrase names the topic; the question is the fallback
                "topic": next((m["missing"] for m in members if m["missing"]), members[0]["question"]),
                "count": len(members),
                "missing": sum(m["verdict"] == "missing" for m in members),
                "partial": sum(m["verdict"] == "partial" for m in members),
                "questions": [{"question": m["question"], "verdict": m["verdict"], "source": m["source"],
                               "passages": [_excerpt(p) for p in m["passages"][:1]]} for m in members],
            })
    summary = coverage_summary([q["verdict"] for q in graded])
    summary["ungraded"] = len(questions) - len(graded)
    summary["sources"] = {s: sum(q["source"] == s for q in questions) for s in ("pasted", "history")}
    return {"summary": summary, "topics": topics}, used


async def _overlaps(job: Job, build: dict[str, Any], cfg: dict[str, Any],
                    chunks: list[dict[str, Any]]) -> dict[str, Any]:
    job.progress("scan", 0, 1)
    embedder = build_node("embed", cfg["embed"])
    vecs = await retrieval.chunk_vectors({c["id"]: c for c in chunks}, embedder.embed_key())
    have = [c for c in chunks if c["id"] in vecs and not c["is_table"]]
    pairs: list[tuple[int, int, float]] = []
    if have:
        matrix = np.stack([vecs[c["id"]] for c in have]).astype(np.float32)
        pairs = await asyncio.to_thread(similar_pairs, matrix, [c["document_id"] for c in have],
                                        NEAR_SIM, MAX_PAIRS * 3)
    job.progress("scan", 1, 1)
    duplicates, candidates = [], []
    for i, j, sim in pairs:
        pair = {"a": _excerpt(have[i]), "b": _excerpt(have[j]), "similarity": round(sim, 4)}
        if sim >= DUPLICATE_SIM:
            duplicates.append(pair)
        elif len(candidates) < MAX_PAIRS:
            candidates.append(pair)

    contradictions = []
    if candidates:
        provider, opts = evaluate.llm_settings(cfg)
        batches = [candidates[i:i + PAIR_BATCH] for i in range(0, len(candidates), PAIR_BATCH)]
        checked, _ = await evaluate.gather_tolerant([_check_pairs(provider, opts, b) for b in batches],
                                                     job, "contradictions")
        for b, res in zip(batches, checked):
            for k, pair in enumerate(b):
                r = (res or {}).get(k)
                if r and r["contradiction"]:
                    contradictions.append({**pair, "explanation": r["explanation"]})
    return {"duplicates": duplicates[:MAX_PAIRS], "contradictions": contradictions,
            "pairs_checked": len(candidates)}


def _usage(chunks: list[dict[str, Any]], used: set[str], n_questions: int) -> dict[str, Any]:
    docs: dict[str, dict[str, Any]] = {}
    for c in chunks:
        d = docs.setdefault(c["document_id"], {"document_id": c["document_id"], "document": c["document"],
                                               "chunks": 0, "used": 0})
        d["chunks"] += 1
        d["used"] += c["id"] in used
    rows = sorted(docs.values(), key=lambda d: (d["used"] / max(1, d["chunks"]), d["document"]))
    return {"questions": n_questions, "chunks": len(chunks), "chunks_used": sum(d["used"] for d in rows),
            "unused_documents": sum(d["used"] == 0 for d in rows), "documents": rows}


async def run_report(job: Job, report_id: str, project_id: str, version: dict[str, Any],
                     extra: list[str]) -> dict[str, Any]:
    try:
        return await _run_report(job, report_id, project_id, version, extra)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE corpus_reports SET status='failed', error=? WHERE id=?", (str(e), report_id))
        raise


async def _run_report(job: Job, report_id: str, project_id: str, version: dict[str, Any],
                      extra: list[str]) -> dict[str, Any]:
    cfg = sync.version_config(version)
    build = await evaluate.ready_build(project_id, cfg, job)
    chunks = await db.fetch_all(
        "SELECT c.id, c.document_id, c.text, c.text_sha, c.is_table, c.heading_path, c.page_start,"
        " d.filename AS document FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE c.build_id=? ORDER BY c.document_id, c.ordinal", (build["id"],))
    questions = await real_questions(project_id, extra)
    coverage, used = await _coverage(job, build, cfg, questions)
    overlaps = await _overlaps(job, build, cfg, chunks)
    result = {"coverage": coverage, **overlaps, "usage": _usage(chunks, used, len(questions))}
    async with db.tx() as c:
        await c.execute("UPDATE corpus_reports SET status='ready', result=?, build_id=? WHERE id=?",
                        (db.dumps(result), build["id"], report_id))
    s = coverage["summary"]
    return {"report_id": report_id, "questions": s["n"], "gaps": len(coverage["topics"]),
            "contradictions": len(overlaps["contradictions"])}


def to_markdown(report: dict[str, Any], project_name: str) -> str:
    """The report as a Markdown content backlog (FR-2.31)."""
    r = report["result"]
    cov, usage = r["coverage"], r["usage"]
    s = cov["summary"]
    out = [f"# Corpus health — {project_name}", "",
           f"Generated {report['created_at'][:16].replace('T', ' ')} UTC · version v{report.get('version') or '?'}", ""]
    out += ["## Coverage", ""]
    if s["n"]:
        out.append(f"{s['covered']} of {s['n']} real questions ({round(s['covered_rate'] * 100)}%) are fully answered "
                   f"by the documents; {s['partial']} partially, {s['missing']} not at all.")
    else:
        out.append("No real questions yet — ask some in the Playground or paste a list when you run the report.")
    out += ["", "## Content backlog", ""]
    if not cov["topics"]:
        out.append("No gaps found.")
    for i, t in enumerate(cov["topics"], start=1):
        out.append(f"{i}. **{t['topic']}** — {t['count']} question{'s' if t['count'] != 1 else ''} "
                   f"({t['missing']} missing, {t['partial']} partial)")
        out += [f"   - {q['question']}" for q in t["questions"][:5]]
    out += ["", "## Contradictions", ""]
    if not r["contradictions"]:
        out.append(f"None found in the {r['pairs_checked']} most similar passage pairs checked.")
    for c in r["contradictions"]:
        out += [f"- **{c['a']['document']}** vs **{c['b']['document']}**: {c['explanation']}"]
    out += ["", "## Duplicate content", ""]
    out += [f"- {d['a']['document']} ≈ {d['b']['document']} (similarity {d['similarity']:.2f})"
            for d in r["duplicates"]] or ["None found."]
    out += ["", "## Unused content", ""]
    if usage["questions"]:
        out += [f"{usage['chunks_used']} of {usage['chunks']} chunks were retrieved by the {usage['questions']} "
                f"questions; {usage['unused_documents']} document(s) never were.", "",
                "| Document | Chunks used |", "|---|---|"]
        out += [f"| {d['document']} | {d['used']} / {d['chunks']} |" for d in usage["documents"]]
    else:
        out.append("Needs real questions to measure.")
    return "\n".join(out) + "\n"
