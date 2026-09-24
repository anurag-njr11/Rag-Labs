"""Pure scoring helpers for auto-generated eval sets. No I/O.

Gold labels are build-independent: an item names its source document and a
verbatim evidence quote, so a retrieved chunk from *any* chunking of that
document counts as a hit if it contains the evidence.
"""

from __future__ import annotations

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


def is_hit(chunk: dict[str, Any], item: dict[str, Any]) -> bool:
    return chunk.get("document_id") == item["document_id"] and contains_evidence(chunk.get("text", ""), item["evidence"])


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
        return {"n": 0, "k": k, "hit_at_1": 0.0, "hit_at_3": 0.0, "hit_at_k": 0.0, "mrr": 0.0}

    def rate(cut: int) -> float:
        return round(sum(1 for r in ranks if r is not None and r <= cut) / n, 4)

    return {
        "n": n,
        "k": k,
        "hit_at_1": rate(1),
        "hit_at_3": rate(3),
        "hit_at_k": rate(k),
        "mrr": round(sum(1 / r for r in ranks if r is not None) / n, 4),
    }


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
