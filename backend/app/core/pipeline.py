"""The pipeline document: a JSON object mapping each slot to a node type and
its parameters. The runtime executes it, the UI edits it, and later phases'
sweeps will mutate it — so all pipeline behaviour lives here and in the
registry, never in the frontend.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .cache import stable_hash
from .node import SLOT_BY_NAME, SLOTS, field_effects, get_spec, slot_types

# Bump to invalidate every existing build when indexing internals change.
# v2: exact-match index gained "heading" keys.
INDEX_SCHEMA_VERSION = 2

PipelineConfig = dict[str, dict[str, Any]]


class PipelineError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("; ".join(f"{e['slot']}: {e['message']}" for e in errors))


def default_for(slot: str, type_: str) -> dict[str, Any]:
    spec = get_spec(slot, type_)
    return {"type": type_, **spec.cls.Config().model_dump(mode="json")}


def validate_pipeline(cfg: dict[str, Any]) -> PipelineConfig:
    """Validate and normalise: every slot present, every default filled in,
    unknown slots/types/fields rejected."""
    errors: list[dict[str, Any]] = []
    unknown = set(cfg) - set(SLOT_BY_NAME)
    for slot in sorted(unknown):
        errors.append({"slot": slot, "field": None, "message": "unknown slot"})

    out: PipelineConfig = {}
    for s in SLOTS:
        node_cfg = cfg.get(s.name)
        if not isinstance(node_cfg, dict) or "type" not in node_cfg:
            errors.append({"slot": s.name, "field": "type", "message": "missing node type"})
            continue
        type_ = node_cfg["type"]
        try:
            spec = get_spec(s.name, type_)
        except KeyError:
            errors.append({"slot": s.name, "field": "type", "message": f"unknown type {type_!r}"})
            continue
        params = {k: v for k, v in node_cfg.items() if k != "type"}
        try:
            model = spec.cls.Config(**params)
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"]) or None
                errors.append({"slot": s.name, "field": loc, "message": err["msg"]})
            continue
        out[s.name] = {"type": type_, **model.model_dump(mode="json")}

    if errors:
        raise PipelineError(errors)
    return out


def rebuild_part(cfg: PipelineConfig) -> dict[str, Any]:
    """The subset of the pipeline that determines the index: node types of
    rebuild slots, plus every field whose effect is 'rebuild'."""
    part: dict[str, Any] = {}
    for s in SLOTS:
        node_cfg = cfg[s.name]
        spec = get_spec(s.name, node_cfg["type"])
        effects = field_effects(s.name, spec.cls.Config)
        fields = {k: node_cfg[k] for k, eff in effects.items() if eff == "rebuild"}
        if s.effect == "rebuild" or fields:
            part[s.name] = {"type": node_cfg["type"], **fields}
    return part


def index_config_hash(cfg: PipelineConfig) -> str:
    return stable_hash({"v": INDEX_SCHEMA_VERSION, "index": rebuild_part(cfg)})[:16]


def with_defaults(cfg: dict[str, Any]) -> PipelineConfig:
    """Fill fields that didn't exist when a config was saved with their current
    defaults, so old versions compare cleanly with new ones. Never raises."""
    out: PipelineConfig = {}
    for slot, node_cfg in cfg.items():
        if not isinstance(node_cfg, dict) or "type" not in node_cfg:
            out[slot] = node_cfg
            continue
        try:
            out[slot] = {**default_for(slot, node_cfg["type"]), **node_cfg}
        except KeyError:  # unknown slot or type — leave as is
            out[slot] = node_cfg
    return out


def diff_pipelines(before: PipelineConfig, after: PipelineConfig) -> list[dict[str, Any]]:
    before, after = with_defaults(before), with_defaults(after)
    changes: list[dict[str, Any]] = []
    for s in SLOTS:
        a, b = before.get(s.name, {}), after.get(s.name, {})
        if a.get("type") != b.get("type"):
            changes.append(
                {"slot": s.name, "field": "type", "before": a.get("type"),
                 "after": b.get("type"), "effect": s.effect}
            )
            continue
        effects = field_effects(s.name, get_spec(s.name, b["type"]).cls.Config)
        for key in sorted((set(a) | set(b)) - {"type"}):
            if a.get(key) != b.get(key):
                changes.append(
                    {"slot": s.name, "field": key, "before": a.get(key),
                     "after": b.get(key), "effect": effects.get(key, s.effect)}
                )
    return changes


def catalog() -> list[dict[str, Any]]:
    """Everything the UI needs to render the configuration editor."""
    out = []
    for s in SLOTS:
        types = []
        for type_, spec in slot_types(s.name).items():
            ok, reason = spec.available()
            types.append(
                {
                    "type": type_,
                    "title": spec.title,
                    "description": spec.description,
                    "available": ok,
                    "unavailable_reason": reason,
                    "exact": spec.exact,
                    "exact_when": getattr(spec.cls, "exact_when", None),
                    "schema": spec.cls.Config.model_json_schema(),
                    "effects": field_effects(s.name, spec.cls.Config),
                    "defaults": default_for(s.name, type_),
                }
            )
        out.append(
            {"slot": s.name, "title": s.title, "description": s.description,
             "effect": s.effect, "types": types}
        )
    return out


RECOMMENDED = {
    "parse": "pymupdf4llm",
    "chunk": "structure_aware",
    "embed": "fastembed",
    "vector_store": "faiss",
    "retrieve": "fused",
    "rerank": "none",
    "prompt": "cited_qa",
}


def recommended_pipeline() -> PipelineConfig:
    """Sensible defaults: local, free, exact vector search, and the first LLM
    provider that has a key configured."""
    from ..llm.provider import PROVIDERS, availability

    gen = next((p for p in PROVIDERS if availability(p)[0]), "gemini")
    return validate_pipeline(
        {slot: default_for(slot, t) for slot, t in {**RECOMMENDED, "generate": gen}.items()}
    )
