"""Starter questions for a project's empty chat, drawn from its own corpus.

Sources, first that yields anything wins:
  eval     — questions from the latest ready eval set (grounded and already validated)
  headings — "Summarize the “X” section" for substantive headings in the active build
  recent   — the project's own recent successful questions
"""
from __future__ import annotations

import re
from typing import Any

from .. import db
from ..core.pipeline import index_config_hash
from . import sync

GENERIC_HEADINGS = {
    "introduction", "overview", "contents", "table of contents", "toc", "index", "references",
    "bibliography", "appendix", "acknowledgements", "acknowledgments", "abstract", "summary",
    "conclusion", "conclusions", "notes", "see also", "footnotes", "preface", "foreword",
}
# "2.3 ", "4) ", "IV. ", "Chapter 3: " — but not the "I" of "Installation".
_NUMBERING = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?|[IVX]+[.)])\s+|^(?:chapter|section|part)\s+[\dIVX]+[.:]?\s*", re.I)


def _round_robin(rows: list[dict[str, Any]], n: int, key: str = "document_id") -> list[dict[str, Any]]:
    """Take rows in order, spreading picks across documents before reusing one."""
    picked: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for strict in (True, False):
        for r in rows:
            if len(picked) == n:
                return picked
            if r in picked or (strict and r[key] in seen_docs):
                continue
            picked.append(r)
            seen_docs.add(r[key])
    return picked


def clean_heading(path: str) -> str | None:
    """Last segment of a heading path, stripped of markup and numbering; None if not worth asking about."""
    h = path.split(" > ")[-1]
    h = re.sub(r"[`*_#]+", "", h).strip().strip(":.").strip()
    h = _NUMBERING.sub("", h).strip()
    if not (3 <= len(h) <= 70) or not re.search(r"[A-Za-z]{3}", h) or h.lower() in GENERIC_HEADINGS:
        return None
    return h


async def _from_eval(project_id: str, n: int) -> list[str]:
    s = await db.fetch_one("SELECT id FROM eval_sets WHERE project_id=? AND status='ready'"
                           " ORDER BY created_at DESC LIMIT 1", (project_id,))
    if not s:
        return []
    rows = await db.fetch_all(
        "SELECT i.question, i.document_id FROM eval_items i JOIN documents d ON d.id = i.document_id"
        " WHERE i.eval_set_id=? AND i.valid=1 AND length(i.question) <= 160 ORDER BY i.ordinal", (s["id"],))
    return [r["question"] for r in _round_robin(rows, n)]


async def _from_headings(project_id: str, n: int) -> list[str]:
    v = await sync.active_version(project_id)
    if not v:
        return []
    b = await db.fetch_one("SELECT id FROM index_builds WHERE project_id=? AND index_config_hash=? AND status='ready'",
                           (project_id, index_config_hash(db.loads(v["config"]))))
    if not b:
        return []
    # Nested sections before top-level ones (often just the document title), then the
    # sections with the most chunks — the substantive ones.
    rows = await db.fetch_all(
        "SELECT heading_path, document_id, COUNT(*) AS n, MIN(ordinal) AS first FROM chunks"
        " WHERE build_id=? AND heading_path != '' GROUP BY document_id, heading_path"
        " ORDER BY instr(heading_path, ' > ') > 0 DESC, n DESC, first", (b["id"],))
    seen: set[str] = set()
    candidates = []
    for r in rows:
        h = clean_heading(r["heading_path"])
        if h and h.lower() not in seen:
            seen.add(h.lower())
            candidates.append({**r, "heading": h})
    return [f"Summarize the “{r['heading']}” section" for r in _round_robin(candidates, n)]


async def _from_recent(project_id: str, n: int) -> list[str]:
    rows = await db.fetch_all(
        "SELECT question FROM runs WHERE project_id=? AND kind='chat' AND status='ok' AND question != ''"
        " AND length(question) <= 160 ORDER BY created_at DESC LIMIT 50", (project_id,))
    out: list[str] = []
    for r in rows:
        q = r["question"].strip()
        if q and q not in out:
            out.append(q)
        if len(out) == n:
            break
    return out


async def suggestions(project_id: str, n: int = 3) -> dict[str, Any]:
    for source, fn in (("eval", _from_eval), ("headings", _from_headings), ("recent", _from_recent)):
        qs = await fn(project_id, n)
        if qs:
            return {"source": source, "questions": qs}
    return {"source": "none", "questions": []}
