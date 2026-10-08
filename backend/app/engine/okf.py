"""Open Knowledge Format (OKF v0.2): bundle import (FR-3.18), metadata-aware retrieval (FR-3.19) and
bundle export (FR-3.20).

An OKF bundle is a directory tree of Markdown with YAML front matter; `type` is the only required key,
and a consumer must not reject a bundle for missing fields, unknown types or broken links. So import
keeps every Markdown file it can read and skips the rest with a reason. Export writes the corpus back
out as a conformant bundle: each document's text with its provenance (`sources`), trust tier (from
`verified`), lifecycle (`status`, `stale_after`), usage, and what the latest Corpus Health report said.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .. import db
from ..core.cache import stable_hash
from ..core.node import build_node
from ..core.pipeline import rebuild_part, recommended_pipeline, with_defaults
from ..ingest import builder
from ..ingest.documents import DocumentError, create_document
from ..ingest.loaders import strip_front_matter
from . import sync

MAX_ENTRIES = 2000
MAX_TOTAL_MB = 200
TIERS = ("human", "process", "agent", "unverified")


def trust_tier(verified: Any) -> str:
    """OKF trust tier from `verified`: "human:…" / "process:…" / "agent:…" prefixes; `true` or a review
    date counts as human review; anything else is unverified."""
    if verified is True or isinstance(verified, (date, datetime)):
        return "human"
    if isinstance(verified, str):
        head = verified.split(":", 1)[0].strip().lower()
        if head in ("human", "process", "agent"):
            return head
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", verified.strip()):
            return "human"
    return "unverified"


# --- import (FR-3.18) -------------------------------------------------------------


async def import_bundle(project_id: str, data: bytes) -> dict[str, Any]:
    """Create a document per Markdown file in the zip. The path inside the bundle is kept in the name
    (`guides/setup.md` → `guides__setup.md`), so same-named files in different folders don't collide."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DocumentError("That isn't a zip file. Export or zip the bundle's folder and upload the .zip.") from e
    entries = [i for i in zf.infolist() if not i.is_dir()]
    if len(entries) > MAX_ENTRIES:
        raise DocumentError(f"The bundle has {len(entries)} files; the limit is {MAX_ENTRIES}.")
    if sum(i.file_size for i in entries) > MAX_TOTAL_MB * 1024 * 1024:
        raise DocumentError(f"The bundle unpacks to more than {MAX_TOTAL_MB} MB.")
    def junk(info: zipfile.ZipInfo) -> bool:
        return any(p.startswith(".") or p == "__MACOSX" for p in PurePosixPath(info.filename.replace("\\", "/")).parts)

    entries = [i for i in entries if not junk(i)]
    # A zipped folder (everything under one top directory): paths start below it.
    tops = {PurePosixPath(i.filename.replace("\\", "/")).parts[0] for i in entries}
    strip_top = len(tops) == 1 and all(len(PurePosixPath(i.filename).parts) > 1 for i in entries)
    created, duplicates, skipped, errors = [], [], [], []
    for info in entries:
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.suffix.lower() not in (".md", ".markdown"):
            skipped.append({"path": str(path), "reason": "not Markdown (references, data and code are kept "
                                                          "out of the index)"})
            continue
        rel = [p for p in path.parts[1 if strip_top else 0:] if p not in ("", ".", "..")]
        try:
            doc, new = await create_document(project_id, "__".join(rel), zf.read(info))
            (created if new else duplicates).append({"id": doc["id"], "filename": doc["filename"]})
        except DocumentError as e:
            errors.append({"path": str(path), "error": str(e)})
    return {"created": created, "duplicates": duplicates, "skipped": skipped, "errors": errors}


# --- retrieval policy (FR-3.19) -----------------------------------------------------

DEPRECATED_WEIGHT = 0.5


def apply_policy(fused: list[tuple[str, float]], meta: dict[str, dict[str, Any]], today: str
                 ) -> tuple[list[tuple[str, float]], dict[str, int]]:
    """Drop chunks of documents past `stale_after`, halve the score of `deprecated` ones, and on equal
    scores put better-verified sources first (human > process > agent > unverified)."""
    out, dropped, demoted = [], 0, 0
    for cid, score in fused:
        m = meta.get(cid) or {}
        if m.get("stale_after") and str(m["stale_after"]) < today:
            dropped += 1
            continue
        if str(m.get("status") or "").lower() == "deprecated":
            score *= DEPRECATED_WEIGHT
            demoted += 1
        out.append((cid, score))
    out.sort(key=lambda x: (-round(x[1], 12), TIERS.index(trust_tier((meta.get(x[0]) or {}).get("verified"))), x[0]))
    return out, {"dropped": dropped, "demoted": demoted}


async def chunk_meta(chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not chunk_ids:
        return {}
    rows = await db.fetch_all(
        f"SELECT c.id, o.metadata FROM chunks c LEFT JOIN document_okf o ON o.document_id = c.document_id"
        f" WHERE c.id IN ({','.join('?' * len(chunk_ids))})", tuple(chunk_ids))
    return {r["id"]: db.loads(r["metadata"], {}) for r in rows}


def today() -> str:
    return datetime.now(UTC).date().isoformat()


# --- export (FR-3.20) --------------------------------------------------------------


def _yaml(meta: dict[str, Any]) -> str:
    """Front matter from flat scalars and lists. Strings are JSON-quoted, which is valid YAML."""
    lines = ["---"]
    for k, v in meta.items():
        if v is None or v == [] or v == "":
            continue
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines += [f"  - {json.dumps(x, ensure_ascii=False) if isinstance(x, str) else json.dumps(x)}" for x in v]
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {json.dumps(str(v), ensure_ascii=False)}")
    return "\n".join(lines + ["---", ""])


def _title(text: str, filename: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, flags=re.M)
    return m.group(1).strip() if m else PurePosixPath(filename.replace("__", "/")).stem.replace("_", " ")


async def _body(doc: dict[str, Any], cfg: dict[str, Any]) -> str:
    """The document's text: Markdown as written (front matter removed); other formats as parsed."""
    raw = Path(doc["raw_path"])
    if doc["filename"].lower().endswith((".md", ".markdown")):
        return strip_front_matter(raw.read_text(encoding="utf-8", errors="replace"))
    part = rebuild_part(cfg)
    key = stable_hash({"doc": doc["content_sha"], "parse": part["parse"]})
    parsed = builder.artifacts().get("parsed", key)
    if parsed is None:
        parsed = await asyncio.to_thread(build_node("parse", cfg["parse"]).parse, raw, builder._kind(doc))
    return "\n\n".join(p["text"] for p in parsed["pages"])


async def _findings(project_id: str) -> dict[str, list[str]]:
    """Per document id, notes from the latest ready Corpus Health report."""
    row = await db.fetch_one("SELECT result FROM corpus_reports WHERE project_id=? AND status='ready'"
                             " ORDER BY created_at DESC LIMIT 1", (project_id,))
    res = db.loads(row["result"], {}) if row else {}
    notes: dict[str, list[str]] = {}

    def add(doc_id: Any, note: str) -> None:
        if doc_id:
            notes.setdefault(str(doc_id), []).append(note)

    for pair in res.get("contradictions", []) or []:
        a, b = pair.get("a") or {}, pair.get("b") or {}
        add(a.get("document_id"), f"may contradict {b.get('document', 'another document')}")
        add(b.get("document_id"), f"may contradict {a.get('document', 'another document')}")
    for pair in res.get("duplicates", []) or []:
        a, b = pair.get("a") or {}, pair.get("b") or {}
        add(a.get("document_id"), f"overlaps {b.get('document', 'another document')}")
        add(b.get("document_id"), f"overlaps {a.get('document', 'another document')}")
    for s in (res.get("staleness") or {}).get("documents", []) or []:
        add(s.get("document_id"), "stale: " + ", ".join(s.get("reasons", [])))
    return notes


async def export_bundle(project_id: str, usage: dict[str, int]) -> bytes:
    version = await sync.active_version(project_id)
    # Non-Markdown documents are parsed the way the active version parses them (recommended if none).
    cfg = with_defaults(db.loads(version["config"], {})) if version else recommended_pipeline()
    docs = await db.fetch_all(
        "SELECT d.*, o.metadata AS okf, o.last_modified FROM documents d"
        " LEFT JOIN document_okf o ON o.document_id = d.id WHERE d.project_id=? ORDER BY d.filename", (project_id,))
    notes = await _findings(project_id)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    buf, used, index = io.BytesIO(), set(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in docs:
            okf = db.loads(d["okf"], {})
            try:
                body = await _body(d, cfg)
            except Exception as e:  # an unparseable file still gets its metadata entry
                body = f"(The text of this document couldn't be extracted: {e})"
            path = str(PurePosixPath(d["filename"].replace("__", "/")).with_suffix(".md"))
            stem, n = path[:-3], 2
            while path in used:
                path, n = f"{stem}-{n}.md", n + 1
            used.add(path)
            meta = {
                "type": okf.get("type") or "Reference",
                "title": _title(body, d["filename"]),
                "sources": okf.get("sources") or [d["source_url"] or f"upload:{d['filename']}"],
                "generated": generated,
                "status": okf.get("status"),
                "stale_after": okf.get("stale_after"),
                "verified": okf.get("verified"),
                "trust": trust_tier(okf.get("verified")),
                "last_modified": d["last_modified"],
                "usage_count": usage.get(d["id"], 0),
                "usage_window": "latest 2000 chat runs",
                "x-raglabs-findings": notes.get(d["id"], []),
            }
            zf.writestr(path, _yaml(meta) + "\n" + body.strip() + "\n")
            index.append(f"- [{meta['title']}]({path}) — {meta['trust']}"
                         + (f", {meta['status']}" if meta["status"] else ""))
        zf.writestr("index.md", _yaml({"type": "Index", "title": "Knowledge base", "generated": generated})
                    + "\n# Knowledge base\n\n" + "\n".join(index) + "\n")
    return buf.getvalue()
