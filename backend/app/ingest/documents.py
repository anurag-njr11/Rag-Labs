"""Adding and removing documents. The raw original is always kept on disk for
the document's lifetime: every re-chunk or parser change re-reads it."""

from __future__ import annotations

import asyncio
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .. import db
from ..config import get_settings
from ..core.cache import sha256_bytes
from . import builder
from .jobs import Job
from .loaders import MIME, detect_kind

USER_AGENT = "RAG-Builder/0.1 (+local document ingestion)"


class DocumentError(ValueError):
    pass


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = re.sub(r"[^\w.\- ]+", "_", stem).strip(" ._")[:120] or "document"
    ext = re.sub(r"[^\w]+", "", ext)[:10]
    return f"{stem}.{ext}" if ext else stem


async def create_document(project_id: str, filename: str, data: bytes,
                          source_url: str | None = None) -> tuple[dict[str, Any], bool]:
    """Returns (document, created). A byte-identical duplicate returns the existing document."""
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


async def fetch_url(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    try:
        r = await client.get(url)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise DocumentError(f"{url}: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise DocumentError(f"{url}: {type(e).__name__}") from e
    return r.content, r.headers.get("content-type", "")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT})


async def create_from_url(project_id: str, url: str) -> tuple[dict[str, Any], bool]:
    if urlparse(url).scheme not in ("http", "https"):
        raise DocumentError("Only http(s) URLs are supported.")
    async with _client() as client:
        data, ctype = await fetch_url(client, url)
    return await create_document(project_id, _filename_for(url, ctype), data, source_url=url)


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
            data, _ = await fetch_url(client, sm)
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
                    data, ctype = await fetch_url(client, url)
                    _, new = await create_document(project_id, _filename_for(url, ctype), data, source_url=url)
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
