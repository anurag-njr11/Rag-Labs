"""Pure scoring helpers for auto-generated eval sets. No I/O.

Gold labels are build-independent: an item names its source document and a
verbatim evidence quote, so a retrieved chunk from *any* chunking of that
document counts as a hit if it contains the evidence.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from typing import Any, Iterable

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = set("""a an and are as at be but by can do does for from has have how i if in into is it its of on or
so that the their them then there these this to was were what when where which who why will with you your""".split())

MIN_EVIDENCE_TOKENS = 4
EVIDENCE_COVERAGE = 0.7


def tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def normalize(text: str) -> str:
    return " ".join(tokens(text))


def coverage(evidence: str, text: str) -> float:
    """Share of the evidence's tokens (with multiplicity) that appear in text."""
    ev = Counter(tokens(evidence))
    if not ev:
        return 0.0
    have = Counter(tokens(text))
    return sum(min(n, have[w]) for w, n in ev.items()) / sum(ev.values())


def contains_evidence(text: str, evidence: str, threshold: float = EVIDENCE_COVERAGE) -> bool:
    ev = normalize(evidence)
    if not ev:
        return False
    if f" {ev} " in f" {normalize(text)} ":
        return True
    return coverage(evidence, text) >= threshold


def same_file(source: str, filename: str | None) -> bool:
    """Whether an external system's `source` (a path or URL) names the eval item's document file."""
    def base(s: str) -> str:
        return re.split(r"[/\\]", s.split("?")[0].split("#")[0].rstrip("/\\"))[-1].strip().lower()

    return not filename or base(source) == base(filename)


def is_hit(chunk: dict[str, Any], item: dict[str, Any]) -> bool:
    if not contains_evidence(chunk.get("text", ""), item["evidence"]):
        return False
    if "external_source" in chunk:  # a bring-your-own RAG: match by file name if it names one, else on evidence alone
        return not chunk["external_source"] or same_file(chunk["external_source"], item.get("filename"))
    return chunk.get("document_id") == item["document_id"]


def first_hit_rank(results: Iterable[dict[str, Any]], item: dict[str, Any]) -> int | None:
    for i, r in enumerate(results, start=1):
        if is_hit(r, item):
            return i
    return None


def token_f1(a: str, b: str) -> float:
    ta = [t for t in tokens(a) if t not in _STOP]
    tb = [t for t in tokens(b) if t not in _STOP]
    if not ta or not tb:
        return 0.0
    common = sum((Counter(ta) & Counter(tb)).values())
    if common == 0:
        return 0.0
    p, r = common / len(ta), common / len(tb)
    return 2 * p * r / (p + r)


def summarize(ranks: list[int | None], k: int) -> dict[str, Any]:
    n = len(ranks)
    if n == 0:
        return {"n": 0, "k": k, "hit_at_1": 0.0, "hit_at_3": 0.0, "hit_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}

    def rate(cut: int) -> float:
        return round(sum(1 for r in ranks if r is not None and r <= cut) / n, 4)

    rr = [1 / r if r else 0.0 for r in ranks]
    mean = sum(rr) / n
    half = 1.96 * math.sqrt(sum((x - mean) ** 2 for x in rr) / max(1, n - 1) / n)
    ci = {f"hit_at_{c}": list(wilson(round(rate(cut) * n), n)) for c, cut in (("1", 1), ("3", 3), ("k", k))}
    ci["mrr"] = [round(max(0.0, mean - half), 4), round(min(1.0, mean + half), 4)]
    return {
        "n": n,
        "k": k,
        "ci": ci,
        "hit_at_1": rate(1),
        "hit_at_3": rate(3),
        "hit_at_k": rate(k),
        "mrr": round(sum(1 / r for r in ranks if r is not None) / n, 4),
        # one relevant passage per question, so the ideal DCG is 1 and nDCG@k = 1/log2(rank+1)
        "ndcg_at_k": round(sum(1 / math.log2(r + 1) for r in ranks if r is not None and r <= k) / n, 4),
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials (sane at small n and at 0/n)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def answer_summary(grades: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-item {correct, grounded} verdicts ('yes'|'partial'|'no'; absent = ungraded)."""
    graded = [g for g in grades if g.get("correct")]
    n = len(graded)

    def count(key: str, v: str) -> int:
        return sum(1 for g in graded if g.get(key) == v)

    yes = count("correct", "yes")
    return {
        "n": n, "ungraded": len(grades) - n,
        "correct": yes, "partial": count("correct", "partial"), "wrong": count("correct", "no"),
        "correct_rate": round(yes / n, 4) if n else 0.0, "correct_ci": list(wilson(yes, n)),
        "grounded_rate": round(count("grounded", "yes") / n, 4) if n else 0.0,
        "relevant_rate": round(count("relevant", "yes") / n, 4) if n else 0.0,
        "context_precision": mean([g.get("context_precision") for g in graded]),
        "context_recall": mean([g.get("context_recall") for g in graded]),
        "cost_per_1k": per_1k([g.get("cost_usd") for g in graded]),  # expansion + answer generation (+ checks)
        **answer_latency(graded),
        **verify_summary(graded),
        **execution_summary(graded),
    }


def execution_summary(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """FR-3.17: execution-verified correctness — the share of questions *with tests* whose answer's code
    passed them in the sandbox. Deterministic given the answers. Absent when no question had tests or
    no code ran."""
    ex = [g["execution"] for g in graded if g.get("execution")]
    tested = [e for e in ex if e.get("has_tests") and e.get("status") in ("verified", "unverified")]
    out: dict[str, Any] = {}
    if tested:
        ok = sum(e["status"] == "verified" for e in tested)
        out["exec_verified_rate"] = round(ok / len(tested), 4)
        out["exec_verified_ci"] = list(wilson(ok, len(tested)))
    if ex:
        out["execution"] = {s: sum(e.get("status") == s for e in ex) for s in
                            ("verified", "unverified", "ran_without_tests", "missing_dependency", "sandbox_unavailable",
                             "not_applicable")}
        out["execution"]["tested"] = len(tested)
    return out


def answer_latency(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """p50/p95 of answer time (generation + grounding checks + retries); absent on older runs."""
    ms = [g["answer_ms"] for g in graded if g.get("answer_ms") is not None]
    return {"answer_p50_ms": round(percentile(ms, 0.5), 1), "answer_p95_ms": round(percentile(ms, 0.95), 1)} if ms else {}


def verify_summary(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """Grounding-check roll-up (Verify slot on): share of answers it passed, how many needed a
    retry with more context, and how many checks failed to run. Absent when the check was off."""
    v = [g["verification"] for g in graded if g.get("verification")]
    if not v:
        return {}
    ok = [x for x in v if x["status"] == "ok"]
    return {"verify": {
        "checked": len(ok), "errors": len(v) - len(ok),
        "pass_rate": round(sum(1 for x in ok if x["grounded"]) / len(ok), 4) if ok else None,
        "retried": sum(1 for x in v if x["attempt"] > 0),
        "mean_score": mean([x["score"] for x in ok]),
    }}


def mean(values: list[float | None]) -> float | None:
    """Mean of the scored values (None = not scored); None if nothing was scored."""
    v = [x for x in values if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def per_1k(costs: list[float | None]) -> float | None:
    """USD per 1,000 queries from per-query costs; None if any cost is unknown (or no queries)."""
    if not costs or any(c is None for c in costs):
        return None
    return round(sum(costs) / len(costs) * 1000, 4)  # type: ignore[arg-type]


def context_precision(relevant: list[bool]) -> float:
    """Rank-weighted contextual precision: mean of precision@i over the relevant positions i
    (0 when no passage is relevant)."""
    hits, total = 0, 0.0
    for i, rel in enumerate(relevant, start=1):
        if rel:
            hits += 1
            total += hits / i
    return round(total / hits, 4) if hits else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def sample_chunks(chunks: list[dict[str, Any]], n: int, seed: int = 0,
                  min_tokens: int = 40) -> list[dict[str, Any]]:
    """Deterministic round-robin across documents so every document is represented."""
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for c in sorted(chunks, key=lambda c: (c["document_id"], c["ordinal"])):
        if c.get("is_table") or c.get("token_count", 0) < min_tokens:
            continue
        by_doc.setdefault(c["document_id"], []).append(c)
    rng = random.Random(seed)
    queues = []
    for doc_id in sorted(by_doc):
        pool = by_doc[doc_id][:]
        rng.shuffle(pool)
        queues.append(pool)
    out: list[dict[str, Any]] = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop())
    return out
