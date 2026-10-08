"""Recipe gallery (FR-3.26): pipeline configurations to share and fork.

Built-in recipes are curated starting points, each built on the recommended pipeline so they stay
valid as node types gain fields. Saved recipes are a project's pipeline kept by name. Sharing needs
no server: the UI puts a recipe in a link (base64url JSON in the URL fragment) that any install can
import. Forking into a project makes it portable first: a corpus-specific adapter is dropped, and
an LLM provider that isn't connected on this install is replaced by the project's own.
"""

from __future__ import annotations

import copy
from typing import Any

from .. import db
from ..core.pipeline import default_for, recommended_pipeline, validate_pipeline, with_defaults
from ..llm import provider as llm

BUILTIN: list[dict[str, Any]] = [
    {"id": "builtin-fast", "name": "Fast & cheap", "tags": ["speed", "cost"],
     "description": "Dense search only, no reranker, a small context budget and concise answers. For high-volume FAQ bots.",
     "patch": {"retrieve": {"type": "dense", "top_k": 5}, "prompt": {"type": "concise", "max_context_tokens": 2000}}},
    {"id": "builtin-accurate", "name": "Accurate: hybrid + rerank", "tags": ["quality"],
     "description": "Dense + keyword search, then a cross-encoder reranker keeps the best 5. The strong conventional baseline.",
     "patch": {"retrieve": {"type": "hybrid", "top_k": 20}, "rerank": {"type": "cross_encoder", "top_n": 5}}},
    {"id": "builtin-technical", "name": "Technical docs & error messages", "tags": ["code", "exact"],
     "description": "Heading-aware chunks, fused dense + keyword + exact lookup with defining sections pinned — for API "
                    "references, stack traces and symbol names.",
     "patch": {"chunk": {"type": "structure_aware"}, "retrieve": {"type": "fused", "pin_definitions": True}}},
    {"id": "builtin-multipart", "name": "Multi-part questions", "tags": ["quality"],
     "description": "Query decomposition: each part of a compound question is searched and gets its own evidence in the top-k.",
     "patch": {"retrieve": {"type": "fused", "query_expansion": "decompose", "top_k": 10}}},
    {"id": "builtin-agentic", "name": "Agentic research", "tags": ["quality", "slow"],
     "description": "An LLM planner searches in up to 4 steps with context offloading. Slower and costlier — compare it "
                    "against hybrid + rerank on the leaderboard first.",
     "patch": {"retrieve": {"type": "agentic", "max_steps": 4, "offload": True, "top_k": 8}}},
    {"id": "builtin-hardened", "name": "Hardened for production", "tags": ["safety"],
     "description": "Delimited untrusted sources, output validation, a grounding check that retries with more context, "
                    "and metadata-aware retrieval (no stale or deprecated documents first).",
     "patch": {"prompt": {"injection_guard": "delimited"}, "retrieve": {"okf_policy": True},
               "verify": {"type": "grounding_check", "on_fail": "retry_with_more_context", "max_retries": 1,
                          "validate_output": True}}},
    {"id": "builtin-cached", "name": "FAQ bot with a semantic cache", "tags": ["cost", "speed"],
     "description": "Repeated questions are answered from the cache (cosine ≥ 0.95, numbers must match) with no retrieval "
                    "or model call.",
     "patch": {"cache": {"type": "semantic", "threshold": 0.95}, "prompt": {"type": "concise"}}},
]


def _apply_patch(cfg: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    for slot, fields in patch.items():
        if "type" in fields and fields["type"] != out[slot]["type"]:
            out[slot] = default_for(slot, fields["type"])
        out[slot].update(fields)
    return validate_pipeline(out)


def builtin() -> list[dict[str, Any]]:
    base = recommended_pipeline()
    return [{**{k: r[k] for k in ("id", "name", "description", "tags")}, "builtin": True,
             "config": _apply_patch(base, r["patch"]), "created_at": None} for r in BUILTIN]


async def saved() -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM recipes ORDER BY created_at DESC")
    return [{"id": r["id"], "name": r["name"], "description": r["description"], "tags": db.loads(r["tags"], []),
             "builtin": False, "config": with_defaults(db.loads(r["config"])), "created_at": r["created_at"],
             "source_project": r["source_project"]} for r in rows]


def portable(cfg: dict[str, Any], target: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """A recipe made fit for this install and project -> (config, notes about what changed)."""
    out, notes = copy.deepcopy(with_defaults(cfg)), []
    if out.get("retrieve", {}).get("adapter"):
        out["retrieve"]["adapter"] = ""
        notes.append("Its embedding adapter was trained on another corpus, so it's left out — train one for this project.")
    gen = out.get("generate", {}).get("type")
    connected = gen in llm.PROVIDERS and llm.availability(gen)[0]
    if gen and not connected:
        fallback = (target or {}).get("generate") or recommended_pipeline()["generate"]
        notes.append(f"The recipe answers with “{gen}”, which isn't connected here, so this project's Generate settings "
                     f"({fallback['type']}) are kept.")
        out["generate"] = fallback
    return validate_pipeline(out), notes
