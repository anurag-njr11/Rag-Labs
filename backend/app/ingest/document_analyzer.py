"""Analyze uploaded documents to guide smart configuration recommendations.

Extracts metadata like structure density, code density, table density, language,
and inferred domain to help the recommender engine choose optimal pipeline settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0  # deterministic language detection
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False


@dataclass
class DocumentMetadata:
    """Aggregated metrics from a single document."""
    char_count: int
    table_count: int
    code_density: float  # 0.0–1.0, fraction of lines that look like code
    structure_density: float  # 0.0–1.0, (headings + lists + tables) / total chars
    table_density: float  # 0.0–1.0, table chars / total chars
    avg_heading_depth: float
    language: str  # "en", "ja", etc.
    inferred_domain: str | None  # "technical", "legal", "general"
    ocr_recommended: bool
    has_heavy_images: bool


def _detect_language(text: str) -> str:
    """Detect document language. Falls back to 'en' if detection fails."""
    if not HAS_LANGDETECT or not text.strip():
        return "en"
    try:
        return detect(text[:5000])  # sample first 5000 chars
    except Exception:
        return "en"


def _count_code_lines(text: str) -> tuple[int, int]:
    """Count lines that look like code vs. total lines.

    Returns: (code_line_count, total_line_count)

    Heuristics:
    - Lines with leading whitespace (indentation)
    - Lines containing: (), {}, [], import, def, class, function, etc.
    - Lines with special chars: @, #, //, etc.
    """
    lines = text.split('\n')
    code_lines = 0

    code_patterns = re.compile(
        r'^\s+\S|'  # indented line
        r'(def|class|import|return|if|for|while|try|except|function|const|let|var|=>)\b|'  # keywords
        r'[{}\[\]()]|'  # brackets
        r'\/\/|'  # comments
        r'[=<>!]={1,2}'  # operators
    )

    for line in lines:
        stripped = line.strip()
        if stripped and code_patterns.search(line):
            code_lines += 1

    return code_lines, len(lines)


def _infer_domain(text: str) -> str | None:
    """Infer document domain from keywords and structure.

    Returns: "technical", "legal", "general", or None
    """
    text_lower = text.lower()

    # Technical keywords
    tech_keywords = {
        'api', 'function', 'class', 'method', 'library', 'code', 'algorithm',
        'implementation', 'parameter', 'return', 'exception', 'error', 'debug',
        'deploy', 'server', 'database', 'query', 'http', 'json', 'config'
    }

    # Legal keywords
    legal_keywords = {
        'agreement', 'clause', 'liability', 'warranty', 'copyright', 'license',
        'intellectual property', 'defendant', 'plaintiff', 'court', 'statute',
        'regulation', 'compliance', 'indemnify', 'breach', 'contract'
    }

    tech_count = sum(1 for kw in tech_keywords if kw in text_lower)
    legal_count = sum(1 for kw in legal_keywords if kw in text_lower)

    if tech_count > legal_count and tech_count > 3:
        return "technical"
    if legal_count > tech_count and legal_count > 3:
        return "legal"

    return None  # general


def analyze_document(pages: list[dict[str, Any]]) -> DocumentMetadata:
    """Analyze parsed document pages and extract metadata.

    Args:
        pages: List of parsed page dicts from the parser, each with 'text' and optional 'page' key.

    Returns:
        DocumentMetadata with all metrics extracted.
    """
    if not pages:
        return DocumentMetadata(
            char_count=0, table_count=0, code_density=0.0, structure_density=0.0,
            table_density=0.0, avg_heading_depth=0.0, language="en",
            inferred_domain=None, ocr_recommended=False, has_heavy_images=False
        )

    # Concatenate all text
    full_text = "\n".join(p.get("text", "") for p in pages)
    char_count = len(full_text)

    if char_count == 0:
        return DocumentMetadata(
            char_count=0, table_count=0, code_density=0.0, structure_density=0.0,
            table_density=0.0, avg_heading_depth=0.0, language="en",
            inferred_domain=None, ocr_recommended=False, has_heavy_images=False
        )

    # Count tables (Markdown table rows: | ... | ... |)
    table_pattern = re.compile(r'^\s*\|.*\|\s*$', re.MULTILINE)
    table_matches = list(table_pattern.finditer(full_text))
    table_count = len(set(m.start() // 100 for m in table_matches))  # rough count of table blocks

    # Table density: chars in tables / total chars
    table_chars = sum(len(m.group()) for m in table_matches)
    table_density = table_chars / char_count if char_count > 0 else 0.0

    # Code density: lines of code / total lines
    code_lines, total_lines = _count_code_lines(full_text)
    code_density = code_lines / total_lines if total_lines > 0 else 0.0

    # Structure density: headings, lists, code blocks
    heading_pattern = re.compile(r'^#{1,6}\s+', re.MULTILINE)
    list_pattern = re.compile(r'^[\s]*[-*+]\s+', re.MULTILINE)
    headings = list(heading_pattern.finditer(full_text))
    lists = list(list_pattern.finditer(full_text))

    structure_items = len(headings) + len(lists) + table_count
    structure_density = structure_items / (char_count / 100) if char_count > 0 else 0.0
    structure_density = min(structure_density, 1.0)  # cap at 1.0

    # Average heading depth (1–6)
    heading_levels = [len(m.group()) - 1 for m in headings]  # depth = # count
    avg_heading_depth = sum(heading_levels) / len(heading_levels) if heading_levels else 0.0

    # Language detection
    language = _detect_language(full_text)

    # Infer domain
    inferred_domain = _infer_domain(full_text)

    # OCR recommended: very few chars on many pages suggests scanned images
    page_count = len(pages)
    avg_chars_per_page = char_count / page_count if page_count > 0 else 0
    ocr_recommended = avg_chars_per_page < 500  # very sparse text = likely images

    # Heavy images: heuristic based on low char density + metadata
    has_heavy_images = avg_chars_per_page < 300

    return DocumentMetadata(
        char_count=char_count,
        table_count=table_count,
        code_density=min(code_density, 1.0),
        structure_density=structure_density,
        table_density=min(table_density, 1.0),
        avg_heading_depth=avg_heading_depth,
        language=language,
        inferred_domain=inferred_domain,
        ocr_recommended=ocr_recommended,
        has_heavy_images=has_heavy_images,
    )


def aggregate_corpus_metadata(metadatas: list[DocumentMetadata]) -> dict[str, Any]:
    """Aggregate individual document metadata into corpus-level profile.

    Used by the recommender to make configuration choices.
    """
    if not metadatas:
        return {
            "avg_structure_density": 0.0,
            "avg_code_density": 0.0,
            "total_char_count": 0,
            "total_table_count": 0,
            "estimated_chunks": 0,
            "has_code": False,
            "languages": [],
            "inferred_domains": [],
            "ocr_needed": False,
        }

    total_chars = sum(m.char_count for m in metadatas)
    total_tables = sum(m.table_count for m in metadatas)
    avg_structure = sum(m.structure_density for m in metadatas) / len(metadatas)
    avg_code = sum(m.code_density for m in metadatas) / len(metadatas)

    # Estimate chunk count (assume ~768 char chunks)
    estimated_chunks = max(1, total_chars // 768)

    # Collect unique languages and domains
    languages = list(set(m.language for m in metadatas if m.language))
    domains = list(set(m.inferred_domain for m in metadatas if m.inferred_domain))

    # Check if any doc has code or needs OCR
    has_code = any(m.code_density > 0.05 for m in metadatas)
    ocr_needed = any(m.ocr_recommended for m in metadatas)

    return {
        "avg_structure_density": avg_structure,
        "avg_code_density": avg_code,
        "total_char_count": total_chars,
        "total_table_count": total_tables,
        "estimated_chunks": estimated_chunks,
        "has_code": has_code,
        "languages": languages,
        "inferred_domains": domains,
        "ocr_needed": ocr_needed,
    }
