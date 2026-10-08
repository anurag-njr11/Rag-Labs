"""Cache slot: answer a repeated question from an earlier answer, before retrieving anything.

`semantic` embeds the question with the project's embedder and looks for an earlier question
whose cosine similarity clears the threshold. Plain string caching can't tell "reset my password"
from "how do I reset my password"; a pure similarity cache can't tell "top 10 errors" from
"top 15 errors". So a deterministic guard also requires the numbers and code identifiers in the
two questions to match exactly. The IO lives in engine/answer_cache.py.
"""

from __future__ import annotations

import re

from ..core.node import Node, NodeConfig, register, ui_field


class NoCacheConfig(NodeConfig):
    pass


@register("cache", "none", title="Off", description="Answer every question from scratch.")
class NoCache(Node):
    Config = NoCacheConfig


class SemanticCacheConfig(NodeConfig):
    threshold: float = ui_field(
        0.95, ge=0.8, le=1.0, title="Similarity threshold",
        description="How close (cosine) a new question must be to an earlier one to reuse its answer. "
                    "Lower = more hits, more risk of answering a different question.")
    ttl_hours: int = ui_field(168, ge=1, le=2160, title="Keep answers for (hours)",
                              description="Older cached answers are ignored and pruned. 168 = one week.")
    max_entries: int = ui_field(2000, ge=50, le=20000, advanced=True, title="Max cached answers",
                                description="Per project and configuration; the oldest go first.")


@register("cache", "semantic", title="Semantic cache",
          description="Reuse the answer to a near-identical earlier question: no retrieval, no LLM call. "
                      "Numbers and code identifiers must match exactly. Edits to documents or settings start "
                      "a fresh cache.")
class SemanticCache(Node):
    Config = SemanticCacheConfig


_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_IDENT = re.compile(r"`[^`]+`|\b\w+(?:[._]\w+)+\(\)|\b\w+\(\)|\b\w+(?:[._]\w+)+\b|\b[a-z]+[A-Z]\w*\b")


def guard_terms(question: str) -> list[str]:
    """Numbers and code-like identifiers (`x`, snake_case, dotted.names, camelCase, call()) that must
    be identical for two questions to share an answer, sorted and lower-cased."""
    found = {m.group(0).strip("`").lower() for m in _IDENT.finditer(question)}
    found |= {m.group(0) for m in _NUM.finditer(question)}
    return sorted(found)
