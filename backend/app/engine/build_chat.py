"""Chat-to-build (FR-3.25): a plain-language edit becomes a schema-valid change to the pipeline.

The model never writes a config. It sees a compact catalog of the slots, node types and fields (with
types, ranges and allowed values) and the current draft, and answers with a list of changes
(`slot.type` or `slot.field` → value). The server applies them the way a sweep does (a type change
resets the slot to that type's defaults, keeping shared fields), validates the result against the
pipeline schema, and gives the model one repair round with the errors. What comes back is a draft and
its diff — nothing is saved until the user saves a version.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from ..core.pipeline import PipelineError, catalog, diff_pipelines, validate_pipeline, with_defaults
from . import evaluate
from .sweep import SweepError, apply_override

SYSTEM = """You edit a retrieval-augmented-generation pipeline configuration for a user.
You may only use the slots, types and fields in the catalog, with values allowed by their limits.
Reply with JSON only:
{"changes": [{"path": "<slot>.<field>", "value": <value>}, ...], "explanation": "<one or two sentences>"}
Use "<slot>.type" to switch a slot to another node type. Change only what the request asks for (and
anything that change strictly requires). If the request can't be done with this catalog, return no
changes and say why in the explanation."""


def _short(text: str | None) -> str:
    t = (text or "").split(". ")[0].strip()
    return t[:90] + ("…" if len(t) > 90 else "")


def catalog_text() -> str:
    lines = []
    for slot in catalog():
        lines.append(f"## {slot['slot']} — {_short(slot['description'])}")
        for t in slot["types"]:
            if not t["available"]:
                continue
            lines.append(f"- type {t['type']}: {_short(t['description'])}")
            for name, prop in (t["schema"].get("properties") or {}).items():
                kind = prop.get("type") or "/".join(str(x.get("type")) for x in prop.get("anyOf", []) if x.get("type"))
                bits = [kind]
                if "enum" in prop:
                    bits = ["one of " + "|".join(map(str, prop["enum"]))]
                for k, label in (("minimum", "min"), ("maximum", "max")):
                    if k in prop:
                        bits.append(f"{label} {prop[k]}")
                bits.append(f"default {json.dumps(prop.get('default'))}")
                lines.append(f"    {name} ({', '.join(bits)}){': ' + _short(prop.get('description')) if prop.get('description') else ''}")
    return "\n".join(lines)


def parse(text: str) -> tuple[list[dict[str, Any]], str]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        d = json.loads(m.group(0) if m else text)
    except (ValueError, AttributeError):
        return [], ""
    changes = [c for c in d.get("changes") or [] if isinstance(c, dict) and isinstance(c.get("path"), str)
               and "value" in c and re.fullmatch(r"[a-z_]+\.[a-z_]+", c["path"])]
    return changes, str(d.get("explanation") or "")[:600]


def apply(cfg: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Types first (so fields land on the new type), then fields; raises SweepError / PipelineError."""
    out = copy.deepcopy(with_defaults(cfg))
    for c in sorted(changes, key=lambda c: not c["path"].endswith(".type")):
        apply_override(out, c["path"], c["value"])
    return validate_pipeline(out)


async def propose(cfg: dict[str, Any], instruction: str, provider: str, opts: dict[str, Any]) -> dict[str, Any]:
    base = validate_pipeline(with_defaults(cfg))
    user = (f"Catalog:\n{catalog_text()}\n\nCurrent configuration:\n{json.dumps(base, indent=1)}\n\n"
            f"Request: {instruction}")
    error = ""
    for attempt in range(2):
        prompt = user if not error else f"{user}\n\nYour previous changes were rejected: {error}\nFix them."
        changes, explanation = parse(await evaluate.complete(provider, {**opts, "temperature": 0}, SYSTEM, prompt))
        if not changes:
            return {"config": base, "changes": [], "explanation": explanation or "The model proposed no change.",
                    "attempts": attempt + 1}
        try:
            new = apply(base, changes)
        except (SweepError, PipelineError, ValueError) as e:
            error = str(e)
            continue
        diff = diff_pipelines(base, new)
        return {"config": new, "changes": diff, "explanation": explanation, "attempts": attempt + 1,
                "rebuild": any(c["effect"] == "rebuild" for c in diff)}
    return {"config": base, "changes": [], "error": f"The model's changes didn't fit the schema: {error}",
            "explanation": "", "attempts": 2}
