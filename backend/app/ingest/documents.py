"""Adding and removing documents. The raw original is always kept on disk for
the document's lifetime: every re-chunk or parser change re-reads it."""

from __future__ import annotations

import asyncio
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .. import db
from ..config import get_settings
from ..core.cache import sha256_bytes
from . import builder
from .jobs import Job
from .loaders import MIME, detect_kind

USER_AGENT = "RAGLabs/0.1 (+local document ingestion)"


class DocumentError(ValueError):
    pass


class OKF(BaseModel):
    """Optional OKF document fields (PRD FR-2.30). `usage_count` is computed from runs, never stored."""
    model_config = ConfigDict(extra="ignore")
    status: str | None = Field(None, max_length=40)  # e.g. draft / published / deprecated
    stale_after: date | None = None
    verified: bool | date | None = None
    sources: list[str] | None = Field(None, max_length=50)

    @field_validator("sources", mode="before")
    @classmethod
    def _one_source(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v


_FRONT_MATTER = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S)


def _scalar(s: str) -> str:
    return s.strip().strip("'\"")


def front_matter(text: str) -> dict[str, Any]:
    """Flat `key: value` YAML front matter, plus `[a, b]` and `- item` lists. Enough for the OKF
    fields; anything fancier is ignored rather than half-parsed."""
    # ponytail: not a YAML parser (no nesting, multi-line strings or comments); use one if front matter grows
    m = _FRONT_MATTER.match(text)
    out: dict[str, Any] = {}
    key = None
    for line in m.group(1).splitlines() if m else []:
        item = re.match(r"\s*-\s+(.+)", line)
        if item and key and isinstance(out.get(key), list):
            out[key].append(_scalar(item.group(1)))
            continue
        kv = re.match(r"([A-Za-z_][\w-]*)\s*:\s*(.*)", line)
        if not kv:
            key = None
            continue
        key, val = kv.group(1).lower(), kv.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            out[key] = [_scalar(x) for x in val[1:-1].split(",") if x.strip()]
        else:
            out[key] = _scalar(val) if val else []
    return out


def okf_from_front_matter(data: bytes) -> dict[str, Any]:
    """The valid OKF fields of a Markdown file's front matter; a bad field is dropped, not fatal."""
    out: dict[str, Any] = {}
    for k, v in front_matter(data[:16384].decode("utf-8", errors="replace")).items():
        if k in OKF.model_fields:
            try:
                out.update(OKF.model_validate({k: v}).model_dump(mode="json", exclude_none=True))
            except ValidationError:
                pass
    return out


def iso_from_ms(ms: int | None) -> str | None:
    """Browser File.lastModified (epoch ms) -> ISO datetime; None if absent or nonsense."""
    try:
        return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds") if ms and ms > 0 else None
    except (OverflowError, OSError, ValueError):
        return None


def iso_from_http(value: str | None) -> str | None:
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat(timespec="seconds") if value else None
    except (TypeError, ValueError):
        return None


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = re.sub(r"[^\w.\- ]+", "_", stem).strip(" ._")[:120] or "document"
    ext = re.sub(r"[^\w]+", "", ext)[:10]
    return f"{stem}.{ext}" if ext else stem


async def create_document(project_id: str, filename: str, data: bytes, source_url: str | None = None,
                          last_modified: str | None = None) -> tuple[dict[str, Any], bool]:
    """Returns (document, created). A byte-identical duplicate returns the existing document.
    Markdown front matter's OKF fields and `last_modified` (ISO) go to document_okf."""
    settings = get_settings()
    filename = safe_filename(filename)
    kind = detect_kind(filename)
    if kind is None:
        raise DocumentError(f"{filename}: unsupported type. Use PDF, DOCX, Markdown, text or HTML.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise DocumentError(f"{filename}: larger than {settings.max_upload_mb} MB.")
    if not data.strip():
        raise DocumentError(f"{filename}: file is empty.")
    sha = sha256_bytes(data)
    existing = await db.fetch_one(
        "SELECT * FROM documents WHERE project_id=? AND content_sha=?", (project_id, sha))
    if existing:
        return existing, False

    doc_id = db.new_id()
    raw_dir = settings.raw_dir / doc_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / filename
    await asyncio.to_thread(raw_path.write_bytes, data)
    async with db.tx() as c:
        await c.execute(
            "INSERT INTO documents (id, project_id, filename, source_url, mime, raw_path, content_sha,"
            " size_bytes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)",
            (doc_id, project_id, filename, source_url, MIME[kind], str(raw_path), sha, len(data), db.now_iso()),
        )
        okf = okf_from_front_matter(data) if kind == "markdown" else {}
        if okf or last_modified:
            await c.execute("INSERT INTO document_okf (document_id, metadata, last_modified) VALUES (?, ?, ?)",
                            (doc_id, db.dumps(okf), last_modified))
    return await db.fetch_one("SELECT * FROM documents WHERE id=?", (doc_id,)), True  # type: ignore[return-value]


def _filename_for(url: str, content_type: str, title_hint: str | None = None) -> str:
    path = unquote(urlparse(url).path).rstrip("/")
    base = Path(path).name or urlparse(url).netloc
    ct = content_type.split(";")[0].strip().lower()
    ext = {"application/pdf": ".pdf", "text/markdown": ".md", "text/plain": ".txt",
           "text/x-markdown": ".md"}.get(ct)
    if ext is None:
        ext = Path(base).suffix.lower() if detect_kind(base) else ".html"
    stem = Path(base).stem if detect_kind(base) else (title_hint or base)
    return safe_filename(f"{stem}{ext}")


async def fetch_url(client: httpx.AsyncClient, url: str) -> tuple[bytes, str, str | None]:
    """(body, content type, Last-Modified as ISO or None)."""
    try:
        r = await client.get(url)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise DocumentError(f"{url}: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise DocumentError(f"{url}: {type(e).__name__}") from e
    return r.content, r.headers.get("content-type", ""), iso_from_http(r.headers.get("last-modified"))


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT})


async def create_from_url(project_id: str, url: str) -> tuple[dict[str, Any], bool]:
    if urlparse(url).scheme not in ("http", "https"):
        raise DocumentError("Only http(s) URLs are supported.")
    async with _client() as client:
        data, ctype, modified = await fetch_url(client, url)
    return await create_document(project_id, _filename_for(url, ctype), data, source_url=url, last_modified=modified)


def _sitemap_locs(xml: bytes) -> tuple[list[str], list[str]]:
    """Returns (page urls, nested sitemap urls)."""
    root = ET.fromstring(xml)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    locs = [el.text.strip() for el in root.iter(f"{ns}loc") if el.text]
    if root.tag.endswith("sitemapindex"):
        return [], locs
    return locs, []


async def crawl_sitemap(project_id: str, sitemap_url: str, max_pages: int, job: Job) -> dict[str, Any]:
    max_pages = max(1, min(max_pages, get_settings().sitemap_max_pages))
    pages: list[str] = []
    async with _client() as client:
        queue, seen = [sitemap_url], set()
        while queue and len(pages) < max_pages and len(seen) < 20:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            job.progress("fetch", 0, 0, f"Reading sitemap {sm}")
            data, _, _ = await fetch_url(client, sm)
            try:
                locs, nested = _sitemap_locs(data)
            except ET.ParseError as e:
                raise DocumentError(f"{sm} is not a valid sitemap XML") from e
            pages.extend(u for u in locs if u not in pages)
            queue.extend(nested)
        pages = pages[:max_pages]

        created, skipped, failed = 0, 0, 0
        sem = asyncio.Semaphore(4)
        done = 0

        async def one(url: str) -> None:
            nonlocal created, skipped, failed, done
            async with sem:
                try:
                    data, ctype, modified = await fetch_url(client, url)
                    _, new = await create_document(project_id, _filename_for(url, ctype), data, source_url=url,
                                                   last_modified=modified)
                    created += int(new)
                    skipped += int(not new)
                except DocumentError as e:
                    failed += 1
                    job.log(str(e), "warning")
                done += 1
                job.progress("fetch", done, len(pages), f"Fetched {done}/{len(pages)} pages")

        await asyncio.gather(*(one(u) for u in pages))
    return {"pages": len(pages), "created": created, "duplicates": skipped, "failed": failed}


async def delete_document(project_id: str, doc_id: str) -> bool:
    doc = await db.fetch_one("SELECT * FROM documents WHERE id=? AND project_id=?", (doc_id, project_id))
    if doc is None:
        return False
    await builder.remove_document_everywhere(project_id, doc_id)
    async with db.tx() as c:
        await c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    await asyncio.to_thread(shutil.rmtree, Path(doc["raw_path"]).parent, True)
    return True
