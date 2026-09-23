"""Exact-match keys for error messages and code symbols.

Embeddings smear exact identifiers into near-neighbours that are subtly
wrong. This path extracts *normalised* keys from chunks at index time and
from the question at query time, and matches them exactly.

Normalisation strips the parts of an error that vary between occurrences
(addresses, paths, line numbers, quoted values, numbers, ids, timestamps),
so two instances of the same error collapse to one signature.
"""

from __future__ import annotations

import re

_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b")
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}[\\/]?")
_LINE_NO = re.compile(r"\bline \d+\b", re.I)
_QUOTED = re.compile(r"'[^'\n]{0,200}'|\"[^\"\n]{0,200}\"")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_SPACE = re.compile(r"\s+")

_EXCEPTION = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")
_DOTTED = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_BACKTICK = re.compile(r"`([^`\n]{2,80})`")
_ERROR_CODE = re.compile(r"\b(?:type|code|error_code|errno)\s*[=:]\s*['\"]?([A-Za-z_][\w.\-]{1,60})", re.I)
_ERRORISH = re.compile(
    r"error|exception|warning|traceback|failed|invalid|cannot|can't|unable|not found|should be|must be|expected",
    re.I,
)
_IDENT = re.compile(r"^[A-Za-z_][\w.]*(?:\(\))?$")

# Dotted words that are prose, not code: "e.g", "i.e", version numbers are already excluded by the regex.
_DOTTED_STOP = {"e.g", "i.e", "etc.", "vs.", "a.m", "p.m"}


def normalize(line: str) -> str:
    s = line.strip()
    s = _UUID.sub("<id>", s)
    s = _TIMESTAMP.sub("<time>", s)
    s = _HEX.sub("<addr>", s)
    s = _PATH.sub("<path>", s)
    s = _LINE_NO.sub("line <n>", s)
    s = _QUOTED.sub("'<v>'", s)
    s = _NUMBER.sub("<n>", s)
    s = _SPACE.sub(" ", s).lower()
    return s.strip(" .:;,")


def _signatures(text: str) -> set[str]:
    keys: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if not (8 <= len(line) <= 400) or not _ERRORISH.search(line):
            continue
        sig = normalize(line)
        if len(sig) < 8:
            continue
        keys.add(sig)
        # The message without its trailing detail, e.g. "... [type=x, input_value=...]".
        head = re.split(r"\s\[|\s\(", sig, maxsplit=1)[0].strip(" .:;,")
        if len(head) >= 12 and head != sig:
            keys.add(head)
        # "SomeError: message" → also the message alone.
        if ": " in sig:
            msg = sig.split(": ", 1)[1].strip()
            if len(msg) >= 12:
                keys.add(msg)
    return keys


def _symbols(text: str) -> set[str]:
    keys: set[str] = set()
    for m in _EXCEPTION.finditer(text):
        keys.add(m.group(1).lower())
    for m in _DOTTED.finditer(text):
        tok = m.group(0)
        if tok.lower() in _DOTTED_STOP or len(tok) > 120:
            continue
        low = tok.lower()
        keys.add(low)
        # Also the last two segments, so "BaseModel.model_validate" matches "pydantic.BaseModel.model_validate".
        parts = low.split(".")
        if len(parts) > 2:
            keys.add(".".join(parts[-2:]))
    for m in _BACKTICK.finditer(text):
        tok = m.group(1).strip()
        if _IDENT.match(tok) and ("_" in tok or "." in tok or any(c.isupper() for c in tok[1:])):
            keys.add(tok.rstrip("()").lower())
    for m in _ERROR_CODE.finditer(text):
        keys.add(m.group(1).lower())
    return keys


_HEADING_IDENT = re.compile(r"^[A-Za-z_][\w.]*$")


def _heading_keys(heading_path: str) -> set[str]:
    """Identifiers that *name* the chunk's section, e.g. a heading `int_parsing` or
    `ValidationError`. Such a section is the definition of that identifier, so it
    should outrank chunks that merely mention it (e.g. in example output)."""
    if not heading_path:
        return set()
    last = heading_path.split(" > ")[-1].strip().strip("`*_ ").strip()
    last = last.replace("`", "").rstrip("()")
    if len(last) >= 3 and _HEADING_IDENT.match(last) and (
        "_" in last or "." in last or any(ch.isupper() for ch in last[1:])
    ):
        return {last.lower()}
    return set()


def extract_keys(text: str, heading_path: str = "") -> list[tuple[str, str]]:
    """(kind, key) pairs for a chunk (with its heading path) or a question."""
    out = [("signature", k) for k in sorted(_signatures(text))]
    out += [("symbol", k) for k in sorted(_symbols(text))]
    out += [("heading", k) for k in sorted(_heading_keys(heading_path))]
    return out


def query_keys(question: str) -> list[tuple[str, str]]:
    keys = set(extract_keys(question))
    # A short pasted error may have no "errorish" word; still try it whole.
    whole = normalize(question)
    if 8 <= len(whole) <= 400:
        keys.add(("signature", whole))
    # A bare identifier question like "model_validate" or "ValidationError".
    q = question.strip().strip("`").rstrip("()")
    if _IDENT.match(q):
        keys.add(("symbol", q.lower()))
    # Identifiers written in plain prose: "What is int_parsing?", "how does ConfigDict work".
    for tok in _PROSE_IDENT.findall(question):
        if tok.lower() in _DOTTED_STOP:
            continue
        if "_" in tok or "." in tok or any(ch.isupper() for ch in tok[1:]):
            keys.add(("symbol", tok.lower()))
    return sorted(keys)


_PROSE_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")


# A heading match marks the defining section, so it outweighs any number of
# incidental signature matches in example output (signature + symbol = 3 per chunk).
KIND_WEIGHT = {"signature": 2.0, "symbol": 1.0, "heading": 6.0}
