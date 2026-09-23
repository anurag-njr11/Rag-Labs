"""Format loaders. Every format is normalised to Markdown pages:

    [{"page": 1, "text": "# Heading\n\nBody...\n\n|a|b|\n|---|---|"}, ...]

`page` is None for formats with no pages (Markdown, text, HTML, DOCX).
PDFs are handled by the parser nodes, since that's where parser choice matters.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

Page = dict[str, Any]

EXT_KIND = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdx": "markdown",
    ".rst": "text",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
}

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "markdown": "text/markdown",
    "text": "text/plain",
    "html": "text/html",
}


def detect_kind(filename: str) -> str | None:
    return EXT_KIND.get(Path(filename).suffix.lower())


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_text(path: Path) -> list[Page]:
    return [{"page": None, "text": read_text_file(path)}]


def load_html(path: Path) -> list[Page]:
    import trafilatura

    html = read_text_file(path)
    md = trafilatura.extract(
        html,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_formatting=True,
        favor_recall=True,
    )
    return [{"page": None, "text": md or ""}]


def _docx_table_md(table: Any) -> str:
    rows = []
    for row in table.rows:
        cells = [" ".join(c.text.split()).replace("|", "\\|") for c in row.cells]
        rows.append("|" + "|".join(cells) + "|")
    if not rows:
        return ""
    width = rows[0].count("|") - 1
    return "\n".join([rows[0], "|" + "|".join(["---"] * width) + "|", *rows[1:]])


def load_docx(path: Path) -> list[Page]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    parts: list[str] = []
    # Walk the body in order so tables stay where they appear.
    for block in d.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(block, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "") if p.style is not None else ""
            m = re.match(r"Heading (\d)", style)
            if m:
                parts.append("#" * int(m.group(1)) + " " + text)
            elif style == "Title":
                parts.append("# " + text)
            elif "List" in style:
                parts.append("- " + text)
            else:
                parts.append(text)
        elif tag == "tbl":
            md = _docx_table_md(Table(block, d))
            if md:
                parts.append(md)
    return [{"page": None, "text": "\n\n".join(parts)}]


# --- post-processing & quality ---------------------------------------------

_DIGITS = re.compile(r"\d+")


def _norm_line(line: str) -> str:
    return _DIGITS.sub("#", line.strip().lower())


def strip_repeated_lines(pages: list[Page], edge_lines: int = 2, threshold: float = 0.6) -> int:
    """Remove running headers/footers: short lines near the top or bottom of
    a page that repeat (ignoring digits) on most pages. Headings and table
    rows are never removed. Returns the number of lines removed."""
    texts = [p["text"] for p in pages]
    # Below 3 pages, "repeats on most pages" can't tell a running header
    # from a chapter title.
    if len(texts) < 3:
        return 0

    def edges(text: str) -> list[str]:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[:edge_lines] + lines[-edge_lines:]

    def candidate(line: str) -> bool:
        s = line.strip()
        return bool(s) and len(s) < 100 and not s.startswith(("#", "|"))

    counts: Counter[str] = Counter()
    for t in texts:
        counts.update({_norm_line(ln) for ln in edges(t) if candidate(ln)})
    repeated = {k for k, n in counts.items() if n / len(texts) >= threshold}
    if not repeated:
        return 0

    removed = 0
    for p in pages:
        lines = p["text"].splitlines()
        nonblank = [i for i, ln in enumerate(lines) if ln.strip()]
        edge_idx = set(nonblank[:edge_lines] + nonblank[-edge_lines:])
        kept = []
        for i, ln in enumerate(lines):
            if i in edge_idx and candidate(ln) and _norm_line(ln) in repeated:
                removed += 1
                continue
            kept.append(ln)
        p["text"] = "\n".join(kept)
    return removed


_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")


def count_tables(text: str) -> int:
    n, in_table = 0, False
    for line in text.splitlines():
        if _TABLE_SEP.match(line) and in_table:
            n += 1
        in_table = bool(_TABLE_ROW.match(line))
    return n


def quality(pages: list[Page], *, ocr_used: bool = False, header_lines_removed: int = 0,
            warnings: list[str] | None = None) -> dict[str, Any]:
    chars = sum(len(p["text"].strip()) for p in pages)
    empty = [p["page"] for p in pages if p["page"] is not None and len(p["text"].strip()) < 20]
    tables = sum(count_tables(p["text"]) for p in pages)
    warns = list(warnings or [])
    paged = [p for p in pages if p["page"] is not None]
    if paged and len(empty) == len(paged):
        warns.append("No text extracted — this looks like a scanned PDF. Enable OCR to read it.")
    elif empty:
        warns.append(f"{len(empty)} page(s) have little or no text (scanned images?).")
    if chars == 0 and not paged:
        warns.append("No text extracted.")
    score = "good" if not warns else ("poor" if chars == 0 or (paged and len(empty) == len(paged)) else "fair")
    return {
        "score": score,
        "pages": len(paged) or None,
        "chars": chars,
        "empty_pages": empty[:50],
        "empty_page_count": len(empty),
        "tables": tables,
        "ocr_used": ocr_used,
        "header_lines_removed": header_lines_removed,
        "warnings": warns,
    }
