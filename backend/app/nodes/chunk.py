"""Chunk slot: Markdown pages → chunks.

All strategies work on character spans over a segment's text, so every chunk
can be mapped back to the pages and heading it came from. Markdown tables are
always emitted as single, unsplit chunks, whatever the strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import model_validator

from ..core.node import Node, NodeConfig, register, ui_field

Span = tuple[int, int]
Measure = Callable[[str], int]

_TOKEN = re.compile(r"\w+|[^\w\s]")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n{2,}")


def approx_tokens(text: str) -> int:
    """Word-and-symbol count. Close to, but not identical to, model tokenizers."""
    return len(_TOKEN.findall(text))


def measure_for(unit: str) -> Measure:
    return len if unit == "chars" else approx_tokens


# --- blocks & segments ------------------------------------------------------


@dataclass
class Block:
    kind: Literal["heading", "table", "text"]
    text: str
    page: int | None
    level: int = 0
    title: str = ""


def to_blocks(pages: list[dict[str, Any]]) -> list[Block]:
    blocks: list[Block] = []
    for p in pages:
        page = p.get("page")
        lines = p["text"].splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            if _TABLE_ROW.match(line):
                j = i
                while j < len(lines) and _TABLE_ROW.match(lines[j]):
                    j += 1
                blocks.append(Block("table", "\n".join(ln.strip() for ln in lines[i:j]), page))
                i = j
                continue
            m = _HEADING.match(line)
            if m:
                title = m.group(2).replace("*", "").strip()
                blocks.append(Block("heading", line.strip(), page, len(m.group(1)), title))
                i += 1
                continue
            j = i
            while (j < len(lines) and lines[j].strip() and not _TABLE_ROW.match(lines[j])
                   and not _HEADING.match(lines[j])):
                j += 1
            blocks.append(Block("text", "\n".join(lines[i:j]).strip(), page))
            i = j
    return blocks


@dataclass
class Segment:
    text: str = ""
    block_spans: list[tuple[int, int, int | None]] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)  # (offset, heading path)
    heading_path: str = ""

    def add(self, text: str, page: int | None) -> int:
        if self.text:
            self.text += "\n\n"
        start = len(self.text)
        self.text += text
        self.block_spans.append((start, len(self.text), page))
        return start

    def pages(self, s: int, e: int) -> tuple[int | None, int | None]:
        pages = [pg for bs, be, pg in self.block_spans if bs < e and be > s and pg is not None]
        return (min(pages), max(pages)) if pages else (None, None)

    def heading_at(self, offset: int) -> str:
        path = self.heading_path
        for off, h in self.headings:
            if off <= offset:
                path = h
            else:
                break
        return path


class HeadingStack:
    def __init__(self) -> None:
        self.stack: list[tuple[int, str]] = []

    def push(self, level: int, title: str) -> str:
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, title))
        return self.path

    @property
    def path(self) -> str:
        return " > ".join(t for _, t in self.stack)


# --- span splitting ---------------------------------------------------------


def _trim(text: str, s: int, e: int) -> Span:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def fixed_spans(text: str, size: int, overlap: int, unit: str) -> list[Span]:
    step = max(1, size - overlap)
    spans: list[Span] = []
    if unit == "chars":
        i = 0
        while i < len(text):
            spans.append((i, min(len(text), i + size)))
            if i + size >= len(text):
                break
            i += step
    else:
        toks = [m.span() for m in _TOKEN.finditer(text)]
        i = 0
        while i < len(toks):
            j = min(len(toks), i + size)
            spans.append((toks[i][0], toks[j - 1][1]))
            if j >= len(toks):
                break
            i += step
    return spans


def _split_on(text: str, s: int, e: int, sep: str) -> list[Span]:
    out: list[Span] = []
    i = s
    while i < e:
        j = text.find(sep, i, e)
        if j == -1:
            out.append((i, e))
            break
        out.append((i, j + len(sep)))
        i = j + len(sep)
    return [sp for sp in out if sp[1] > sp[0]]


def _pieces(text: str, s: int, e: int, seps: list[str], size: int, unit: str,
            measure: Measure) -> list[Span]:
    if measure(text[s:e]) <= size:
        return [(s, e)]
    for idx, sep in enumerate(seps):
        if sep == "":
            break
        parts = _split_on(text, s, e, sep)
        if len(parts) > 1:
            out: list[Span] = []
            for ps, pe in parts:
                if measure(text[ps:pe]) <= size:
                    out.append((ps, pe))
                else:
                    out.extend(_pieces(text, ps, pe, seps[idx + 1:], size, unit, measure))
            return out
    # Nothing left to split on: hard cut.
    return [(s + a, s + b) for a, b in fixed_spans(text[s:e], size, 0, unit)]


def merge_pieces(text: str, pieces: list[Span], size: int, overlap: int,
                 measure: Measure) -> list[Span]:
    """Greedily pack contiguous pieces into chunks of at most `size`,
    starting each new chunk with trailing pieces worth up to `overlap`."""
    chunks: list[Span] = []
    cur: list[tuple[Span, int]] = []
    cur_len = 0
    for p in pieces:
        plen = measure(text[p[0]:p[1]])
        if cur and cur_len + plen > size:
            chunks.append((cur[0][0][0], cur[-1][0][1]))
            keep: list[tuple[Span, int]] = []
            kept = 0
            for q in reversed(cur):
                if kept + q[1] > overlap:
                    break
                keep.insert(0, q)
                kept += q[1]
            cur, cur_len = keep, kept
            if cur and cur_len + plen > size:
                cur, cur_len = [], 0
        cur.append((p, plen))
        cur_len += plen
    if cur:
        chunks.append((cur[0][0][0], cur[-1][0][1]))
    return chunks


DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def recursive_spans(text: str, size: int, overlap: int, unit: str,
                    separators: list[str] | None = None) -> list[Span]:
    m = measure_for(unit)
    pieces = _pieces(text, 0, len(text), separators or DEFAULT_SEPARATORS, size, unit, m)
    return merge_pieces(text, pieces, size, overlap, m)


def sentence_spans(text: str, size: int, overlap: int, unit: str) -> list[Span]:
    m = measure_for(unit)
    sents: list[Span] = []
    i = 0
    for br in _SENTENCE_BREAK.finditer(text):
        if br.end() > i:
            sents.append((i, br.end()))
            i = br.end()
    if i < len(text):
        sents.append((i, len(text)))
    pieces: list[Span] = []
    for s, e in sents:
        if m(text[s:e]) <= size:
            pieces.append((s, e))
        else:
            pieces.extend(_pieces(text, s, e, [" ", ""], size, unit, m))
    return merge_pieces(text, pieces, size, overlap, m)


def merge_small(text: str, spans: list[Span], min_size: int, measure: Measure) -> list[Span]:
    if min_size <= 0 or len(spans) < 2:
        return spans
    out: list[Span] = []
    for s, e in spans:
        if out and measure(text[s:e]) < min_size:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    if len(out) > 1 and measure(text[out[0][0]:out[0][1]]) < min_size:
        out[1] = (out[0][0], out[1][1])
        out.pop(0)
    return out


def _heading_only(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(_HEADING.match(ln) for ln in lines)


def absorb_heading_only(text: str, spans: list[Span]) -> list[Span]:
    """A chunk that is nothing but headings retrieves badly; fold it into the
    chunk that follows (or the one before, if it's last)."""
    out: list[Span] = []
    carry: int | None = None
    for s, e in spans:
        if carry is not None:
            s, carry = carry, None
        if _heading_only(text[s:e]):
            carry = s
            continue
        out.append((s, e))
    if carry is not None:
        if out:
            out[-1] = (out[-1][0], len(text))
        else:
            out.append((carry, len(text)))
    return out


# --- configs & nodes --------------------------------------------------------

Unit = Literal["chars", "tokens"]


class _BaseChunkConfig(NodeConfig):
    size: int = ui_field(1000, ge=50, le=20000, title="Chunk size",
                         description="Target size of each chunk, in the chosen unit.")
    overlap: int = ui_field(150, ge=0, le=5000, title="Overlap",
                            description="How much of the previous chunk repeats at the start of the next.")
    unit: Unit = ui_field("chars", title="Size unit",
                          description="Characters, or approximate tokens (words and symbols).")

    @model_validator(mode="after")
    def _overlap_lt_size(self):
        if self.overlap >= self.size:
            raise ValueError("overlap must be smaller than chunk size")
        return self


class FixedConfig(_BaseChunkConfig):
    pass


class RecursiveConfig(_BaseChunkConfig):
    min_chunk_size: int = ui_field(0, ge=0, le=5000, title="Minimum chunk size",
                                   description="Chunks smaller than this merge into their neighbour.")
    separators: list[str] = ui_field(
        DEFAULT_SEPARATORS, advanced=True, title="Separators",
        description="Tried in order; the text is split on the first that produces pieces small enough.",
    )


class SentenceConfig(_BaseChunkConfig):
    min_chunk_size: int = ui_field(0, ge=0, le=5000, title="Minimum chunk size")


class StructureConfig(_BaseChunkConfig):
    heading_depth: int = ui_field(3, ge=1, le=6, title="Heading depth",
                                  description="Start a new section at headings up to this level (1 = only #).")
    include_heading_in_text: bool = ui_field(
        True, title="Prefix heading path",
        description="Add 'Section: A > B' to each chunk so it carries its context when retrieved.",
    )
    min_chunk_size: int = ui_field(0, ge=0, le=5000, title="Minimum chunk size")


class BaseChunker(Node):
    def spans(self, text: str) -> list[Span]:
        raise NotImplementedError

    def chunk(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocks = to_blocks(pages)
        chunks: list[dict[str, Any]] = []
        for seg, is_table in self.segments(blocks):
            if is_table:
                p0, p1 = seg.pages(0, len(seg.text))
                chunks.append(self._chunk(seg.text, p0, p1, seg.heading_path, True))
                continue
            spans = self.spans(seg.text)
            min_size = getattr(self.config, "min_chunk_size", 0)
            spans = merge_small(seg.text, spans, min_size, measure_for(self.config.unit))
            spans = absorb_heading_only(seg.text, spans)
            for s, e in spans:
                s, e = _trim(seg.text, s, e)
                if e <= s:
                    continue
                p0, p1 = seg.pages(s, e)
                chunks.append(self._chunk(seg.text[s:e], p0, p1, seg.heading_at(s), False))
        return chunks

    def segments(self, blocks: list[Block]) -> list[tuple[Segment, bool]]:
        """Default: one flowing segment per document; tables pulled out whole."""
        flow = Segment()
        headings = HeadingStack()
        out: list[tuple[Segment, bool]] = []
        for b in blocks:
            if b.kind == "table":
                t = Segment(heading_path=headings.path)
                t.add(b.text, b.page)
                out.append((t, True))
                continue
            start = flow.add(b.text, b.page)
            if b.kind == "heading":
                flow.headings.append((start, headings.push(b.level, b.title)))
        if flow.text:
            out.insert(0, (flow, False))
        return out

    def _chunk(self, text: str, p0: int | None, p1: int | None, heading: str,
               is_table: bool) -> dict[str, Any]:
        return {"text": text, "page_start": p0, "page_end": p1,
                "heading_path": heading, "is_table": is_table}


@register("chunk", "fixed", title="Fixed size",
          description="Cut every N characters/tokens, ignoring sentence and section boundaries.")
class FixedChunker(BaseChunker):
    Config = FixedConfig

    def spans(self, text: str) -> list[Span]:
        c = self.config
        return fixed_spans(text, c.size, c.overlap, c.unit)


@register("chunk", "recursive", title="Recursive",
          description="Split on paragraphs, then lines, then sentences, then words, until pieces fit.")
class RecursiveChunker(BaseChunker):
    Config = RecursiveConfig

    def spans(self, text: str) -> list[Span]:
        c = self.config
        return recursive_spans(text, c.size, c.overlap, c.unit, c.separators)


@register("chunk", "sentence", title="Sentence packing",
          description="Pack whole sentences into chunks; never cuts mid-sentence unless one is too long.")
class SentenceChunker(BaseChunker):
    Config = SentenceConfig

    def spans(self, text: str) -> list[Span]:
        c = self.config
        return sentence_spans(text, c.size, c.overlap, c.unit)


@register("chunk", "structure_aware", title="Structure-aware (headings)",
          description="One section per heading; long sections split recursively. Best for docs and manuals.")
class StructureChunker(BaseChunker):
    Config = StructureConfig

    def spans(self, text: str) -> list[Span]:
        c = self.config
        return recursive_spans(text, c.size, c.overlap, c.unit)

    def segments(self, blocks: list[Block]) -> list[tuple[Segment, bool]]:
        c: StructureConfig = self.config  # type: ignore[assignment]
        headings = HeadingStack()
        out: list[tuple[Segment, bool]] = []
        cur = Segment()
        for b in blocks:
            if b.kind == "heading" and b.level <= c.heading_depth:
                if cur.text:
                    out.append((cur, False))
                cur = Segment(heading_path=headings.push(b.level, b.title))
                cur.add(b.text, b.page)
            elif b.kind == "table":
                t = Segment(heading_path=headings.path)
                t.add(b.text, b.page)
                out.append((t, True))
            else:
                start = cur.add(b.text, b.page)
                if b.kind == "heading":
                    cur.headings.append((start, headings.push(b.level, b.title)))
        if cur.text:
            out.append((cur, False))
        return out

    def _chunk(self, text, p0, p1, heading, is_table):
        c: StructureConfig = self.config  # type: ignore[assignment]
        if c.include_heading_in_text and heading and not text.lstrip().startswith("#"):
            text = f"Section: {heading}\n\n{text}"
        return super()._chunk(text, p0, p1, heading, is_table)
