"""Parse slot: file on disk → Markdown pages + a parse-quality report.

Parser choice only changes how PDFs are read. Other formats always go through
the shared loaders.
"""

from __future__ import annotations

import functools
import shutil
from pathlib import Path
from typing import Any

from ..core.node import Node, NodeConfig, register, ui_field
from ..ingest import loaders


@functools.cache
def tesseract_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pymupdf

        return bool(pymupdf.get_tessdata())
    except Exception:
        return False


class BaseParser(Node):
    def parse(self, path: Path, kind: str) -> dict[str, Any]:
        warnings: list[str] = []
        ocr_used = False
        if kind == "pdf":
            pages, ocr_used, warnings = self.parse_pdf(path)
        elif kind == "docx":
            pages = loaders.load_docx(path)
        elif kind == "html":
            pages = loaders.load_html(path)
        elif kind in ("markdown", "text"):
            pages = loaders.load_text(path)
        else:
            raise ValueError(f"unsupported document kind {kind!r}")

        removed = 0
        if getattr(self.config, "strip_headers_footers", False):
            removed = loaders.strip_repeated_lines(pages)
        return {
            "pages": pages,
            "quality": loaders.quality(
                pages, ocr_used=ocr_used, header_lines_removed=removed, warnings=warnings
            ),
        }

    def parse_pdf(self, path: Path) -> tuple[list[loaders.Page], bool, list[str]]:
        raise NotImplementedError


class Pymupdf4llmConfig(NodeConfig):
    strip_headers_footers: bool = ui_field(
        True, title="Strip headers & footers",
        description="Remove lines repeated at the top/bottom of most pages.",
    )


@register(
    "parse", "pymupdf4llm", title="PyMuPDF4LLM (Markdown)",
    description="Best default. Keeps headings and turns tables into Markdown tables.",
)
class Pymupdf4llmParser(BaseParser):
    Config = Pymupdf4llmConfig

    def parse_pdf(self, path: Path):
        import pymupdf4llm

        res = pymupdf4llm.to_markdown(str(path), page_chunks=True, show_progress=False)
        pages = [
            {"page": int(r["metadata"].get("page_number") or i + 1), "text": r["text"]}
            for i, r in enumerate(res)
        ]
        return pages, False, []


class PymupdfTextConfig(NodeConfig):
    extract_tables: bool = ui_field(
        True, title="Extract tables",
        description="Detect tables and emit them as Markdown (kept whole when chunking).",
    )
    ocr: bool = ui_field(
        False, title="OCR empty pages",
        description="Run OCR on pages with no text layer. Needs Tesseract installed.",
    )
    strip_headers_footers: bool = ui_field(True, title="Strip headers & footers")


@register(
    "parse", "pymupdf_text", title="PyMuPDF (plain text)",
    description="Fast plain-text extraction, optional table detection and OCR.",
)
class PymupdfTextParser(BaseParser):
    Config = PymupdfTextConfig

    def parse_pdf(self, path: Path):
        import pymupdf

        cfg: PymupdfTextConfig = self.config  # type: ignore[assignment]
        warnings: list[str] = []
        if cfg.ocr and not tesseract_available():
            warnings.append("OCR requested but Tesseract is not installed; skipped.")
        ocr_used = False
        pages = []
        with pymupdf.open(str(path)) as doc:
            for pno, page in enumerate(doc, start=1):
                table_md: list[str] = []
                table_rects: list[Any] = []
                if cfg.extract_tables:
                    try:
                        for t in page.find_tables().tables:
                            md = t.to_markdown().strip()
                            if md:
                                table_md.append(md)
                                table_rects.append(pymupdf.Rect(t.bbox))
                    except Exception:  # table detection is best-effort
                        pass
                blocks = []
                for b in page.get_text("blocks", sort=True):
                    rect = pymupdf.Rect(b[:4])
                    if any(rect.intersects(r) for r in table_rects):
                        continue  # table text is emitted once, as Markdown
                    if b[4].strip():
                        blocks.append(b[4].strip())
                text = "\n\n".join(blocks)
                if len(text.strip()) < 20 and cfg.ocr and tesseract_available():
                    tp = page.get_textpage_ocr(full=True)
                    text = page.get_text("text", textpage=tp)
                    ocr_used = True
                if table_md:
                    text = text + "\n\n" + "\n\n".join(table_md)
                pages.append({"page": pno, "text": text})
        return pages, ocr_used, warnings


class PypdfConfig(NodeConfig):
    strip_headers_footers: bool = ui_field(True, title="Strip headers & footers")


@register(
    "parse", "pypdf", title="pypdf (pure Python)",
    description="Simple text extraction; no table or heading detection.",
)
class PypdfParser(BaseParser):
    Config = PypdfConfig

    def parse_pdf(self, path: Path):
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [
            {"page": i, "text": page.extract_text() or ""}
            for i, page in enumerate(reader.pages, start=1)
        ]
        return pages, False, []
