"""Corpus Health: what the documents can't answer, where they disagree, and what nobody uses.

One report = one background job over a version's build:
- coverage: real questions (Playground/API history + any the user pastes) are retrieved
  against the index; an LLM grades each as covered / partial / missing from the top
  passages (discrete verdicts, temperature 0.3, batched). Gaps are grouped into topics by
  greedy cosine clustering of the question embeddings -> a ranked content backlog.
- duplicates / contradictions: a blockwise cosine scan over the build's cached vectors
  finds cross-document pairs; near-identical pairs are duplicates (no LLM), close pairs
  get an LLM contradiction check.
- retrieval misses: each gap question is re-judged against the top DEEP_PASSAGES of a deep
  retrieval (evaluate.deep_config); if those answer it, the content exists and retrieval missed it.
- unused content: chunks and documents never retrieved by any analysed question.
- staleness: documents marked deprecated, past their OKF `stale_after`, or last modified too long ago.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
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
DEEP_PASSAGES = 15   # re-judge gaps against this many deep-retrieval passages...
DEEP_CHARS = 600     # ...cut shorter, so a batch of 5 stays ~11k tokens
STALE_DAYS = 365

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


def staleness(docs: list[dict[str, Any]], today: date, max_age_days: int = STALE_DAYS) -> list[dict[str, Any]]:
    """Stale documents (FR-2.28), oldest first. `docs`: {id, filename, okf (dict), last_modified (ISO|None)}.
    Reasons: `deprecated` (OKF status), `past_stale_after`, `old` (last modified > max_age_days ago)."""
    out = []
    for d in docs:
        okf = d["okf"]
        reasons = []
        if str(okf.get("status") or "").strip().lower() == "deprecated":
            reasons.append("deprecated")
        if okf.get("stale_after") and okf["stale_after"] < today.isoformat():
            reasons.append("past_stale_after")
        age = (today - date.fromisoformat(d["last_modified"][:10])).days if d["last_modified"] else None
        if age is not None and age > max_age_days:
            reasons.append("old")
        if reasons:
            out.append({"document_id": d["id"], "document": d["filename"], "reasons": reasons,
                        "status": okf.get("status"), "stale_after": okf.get("stale_after"),
                        "last_modified": d["last_modified"], "age_days": age})
    return sorted(out, key=lambda r: (-(r["age_days"] or 0), r["document"]))


def coverage_summary(verdicts: list[str]) -> dict[str, Any]:
    n = len(verdicts)
    counts = {v: verdicts.count(v) for v in VERDICTS}
    return {"n": n, **counts, "covered_rate": round(counts["covered"] / n, 4) if n else 0.0}


# --- LLM steps --------------------------------------------------------------------

async def _judge(provider: str, opts: dict[str, Any], batch: list[dict[str, Any]],
                 key: str = "passages", chars: int = PASSAGE_CHARS) -> dict[int, dict[str, str]]:
    parts = []
    for i, q in enumerate(batch, start=1):
        passages = "\n".join(f"  [{k}] {p['text'][:chars]}" for k, p in enumerate(q[key], start=1))
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
    gaps = await _recheck(job, build, cfg, [q for q in graded if q["verdict"] != "covered"])
    misses = [q for q in gaps if q["cause"] == "retrieval_miss"]
    gaps = [q for q in gaps if q["cause"] != "retrieval_miss"]
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
    summary["retrieval_miss"] = len(misses)
    summary["sources"] = {s: sum(q["source"] == s for q in questions) for s in ("pasted", "history")}
    retrieval_misses = [{"question": m["question"], "verdict": m["verdict"], "source": m["source"]} for m in misses]
    return {"summary": summary, "topics": topics, "retrieval_misses": retrieval_misses}, used


async def _recheck(job: Job, build: dict[str, Any], cfg: dict[str, Any],
                   gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sets each gap's `cause`: `retrieval_miss` if a deep retrieval's top passages answer it, else
    `content_missing`. One extra judge call per JUDGE_BATCH gaps; a failed batch stays a content gap."""
    if not gaps:
        return gaps
    deep = evaluate.deep_config(cfg)
    for q in gaps:
        q["deep"] = (await retrieval.retrieve(RunContext(), build=build, cfg=deep, question=q["question"]))[:DEEP_PASSAGES]
    provider, opts = evaluate.llm_settings(cfg)
    batches = [gaps[i:i + JUDGE_BATCH] for i in range(0, len(gaps), JUDGE_BATCH)]
    judged, _ = await evaluate.gather_tolerant(
        [_judge(provider, opts, b, key="deep", chars=DEEP_CHARS) for b in batches], job, "recheck")
    for b, res in zip(batches, judged):
        for j, q in enumerate(b):
            v = (res or {}).get(j)
            q["cause"] = "retrieval_miss" if v and v["verdict"] == "covered" else "content_missing"
    return gaps


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


async def stale_documents(project_id: str, max_age_days: int = STALE_DAYS) -> dict[str, Any]:
    rows = await db.fetch_all("SELECT d.id, d.filename, o.metadata, o.last_modified FROM documents d"
                              " LEFT JOIN document_okf o ON o.document_id = d.id WHERE d.project_id=?"
                              " ORDER BY d.filename, d.id", (project_id,))
    docs = [{**r, "okf": db.loads(r["metadata"], {})} for r in rows]
    return {"max_age_days": max_age_days, "documents_checked": len(docs),
            "with_dates": sum(bool(d["last_modified"] or d["okf"].get("stale_after")) for d in docs),
            "documents": staleness(docs, datetime.now(UTC).date(), max_age_days)}


async def run_report(job: Job, report_id: str, project_id: str, version: dict[str, Any],
                     extra: list[str], stale_days: int = STALE_DAYS) -> dict[str, Any]:
    try:
        return await _run_report(job, report_id, project_id, version, extra, stale_days)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE corpus_reports SET status='failed', error=? WHERE id=?", (str(e), report_id))
        raise


async def _run_report(job: Job, report_id: str, project_id: str, version: dict[str, Any],
                      extra: list[str], stale_days: int) -> dict[str, Any]:
    cfg = sync.version_config(version)
    build = await evaluate.ready_build(project_id, cfg, job)
    chunks = await db.fetch_all(
        "SELECT c.id, c.document_id, c.text, c.text_sha, c.is_table, c.heading_path, c.page_start,"
        " d.filename AS document FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE c.build_id=? ORDER BY c.document_id, c.ordinal", (build["id"],))
    questions = await real_questions(project_id, extra)
    coverage, used = await _coverage(job, build, cfg, questions)
    overlaps = await _overlaps(job, build, cfg, chunks)
    result = {"coverage": coverage, **overlaps, "usage": _usage(chunks, used, len(questions)),
              "staleness": await stale_documents(project_id, stale_days)}
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
    misses = cov.get("retrieval_misses") or []
    if misses:
        out += ["", "## Retrieval misses", "",
                "The documents answer these (a deeper search found it), but the configured retrieval didn't surface "
                "the passage. Run a sweep on the Evaluate tab or raise `top_k`.", ""]
        out += [f"- {m['question']}" for m in misses]
    out += ["", "## Contradictions", ""]
    if not r["contradictions"]:
        out.append(f"None found in the {r['pairs_checked']} most similar passage pairs checked.")
    for c in r["contradictions"]:
        out += [f"- **{c['a']['document']}** vs **{c['b']['document']}**: {c['explanation']}"]
    out += ["", "## Duplicate content", ""]
    out += [f"- {d['a']['document']} ≈ {d['b']['document']} (similarity {d['similarity']:.2f})"
            for d in r["duplicates"]] or ["None found."]
    stale = r.get("staleness")  # absent in reports made before staleness existed
    if stale is not None:
        out += ["", "## Stale documents", ""]
        why = {"deprecated": "marked deprecated", "past_stale_after": "past stale_after",
               "old": f"not modified in over {stale['max_age_days']} days"}

        def reason(d: dict[str, Any], x: str) -> str:
            extra = {"past_stale_after": f" ({d['stale_after']})",
                     "old": f" (last modified {(d['last_modified'] or '')[:10]})"}.get(x, "")
            return why[x] + extra

        out += [f"- **{d['document']}** — " + "; ".join(reason(d, x) for x in d["reasons"])
                for d in stale["documents"]] or [
            f"None. {stale['with_dates']} of {stale['documents_checked']} documents carry a last-modified "
            "or stale_after date; the rest can't be checked."]
    out += ["", "## Unused content", ""]
    if usage["questions"]:
        out += [f"{usage['chunks_used']} of {usage['chunks']} chunks were retrieved by the {usage['questions']} "
                f"questions; {usage['unused_documents']} document(s) never were.", "",
                "| Document | Chunks used |", "|---|---|"]
        out += [f"| {d['document']} | {d['used']} / {d['chunks']} |" for d in usage["documents"]]
    else:
        out.append("Needs real questions to measure.")
    return "\n".join(out) + "\n"
