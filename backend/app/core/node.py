"""The node contract and registry.

Every pipeline stage ("slot") is filled by one node type. A node type is a class
with a Pydantic `Config` whose JSON schema drives the UI form, so adding or
changing a parameter never touches the frontend.

Each config field has an *effect*:
  - "rebuild": changing it requires re-indexing (feeds the index config hash)
  - "instant": applied at query time

A field inherits its slot's default effect unless it declares its own via
`instant_field(...)` / `rebuild_field(...)`.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

Effect = Literal["rebuild", "instant"]


class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _field(effect: Effect, default: Any, *, advanced: bool = False, **kw: Any) -> Any:
    extra = dict(kw.pop("json_schema_extra", None) or {})
    extra["effect"] = effect
    if advanced:
        extra["advanced"] = True
    return Field(default, json_schema_extra=extra, **kw)


def instant_field(default: Any, **kw: Any) -> Any:
    return _field("instant", default, **kw)


def rebuild_field(default: Any, **kw: Any) -> Any:
    return _field("rebuild", default, **kw)


def ui_field(default: Any, *, advanced: bool = False, **kw: Any) -> Any:
    """A field that inherits its slot's effect but carries UI hints."""
    extra = dict(kw.pop("json_schema_extra", None) or {})
    if advanced:
        extra["advanced"] = True
    return Field(default, json_schema_extra=extra or None, **kw)


# --- trace events -----------------------------------------------------------


@dataclass
class TraceEvent:
    seq: int
    step: str
    ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """Passed to every node. `emit` records a trace step.

    Single-shot nodes emit once. Multi-step nodes (e.g. a future agentic
    retriever) emit many times through the same contract.
    """

    listener: Callable[[TraceEvent], None] | None = None
    events: list[TraceEvent] = field(default_factory=list)

    def emit(
        self,
        step: str,
        *,
        ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        **payload: Any,
    ) -> TraceEvent:
        ev = TraceEvent(
            seq=len(self.events),
            step=step,
            ms=round(ms, 2),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            payload=payload,
        )
        self.events.append(ev)
        if self.listener is not None:
            self.listener(ev)
        return ev

    @contextmanager
    def timed(self, step: str, **payload: Any) -> Iterator[dict[str, Any]]:
        """Time a block and emit it on exit. Mutate the yielded dict to add
        fields (tokens_in, tokens_out, cost_usd, or payload keys)."""
        extra: dict[str, Any] = dict(payload)
        t0 = time.perf_counter()
        yield extra
        ms = (time.perf_counter() - t0) * 1000
        self.emit(
            step,
            ms=ms,
            tokens_in=extra.pop("tokens_in", 0),
            tokens_out=extra.pop("tokens_out", 0),
            cost_usd=extra.pop("cost_usd", 0.0),
            **extra,
        )

    @property
    def totals(self) -> dict[str, float]:
        return {
            "ms": round(sum(e.ms for e in self.events), 2),
            "tokens_in": sum(e.tokens_in for e in self.events),
            "tokens_out": sum(e.tokens_out for e in self.events),
            "cost_usd": round(sum(e.cost_usd for e in self.events), 6),
        }


# --- nodes & registry -------------------------------------------------------


class Node:
    """Base for every node type. Subclasses set `Config` and implement the
    slot-specific method(s); configuration is validated on construction."""

    slot: ClassVar[str]
    type: ClassVar[str]
    Config: ClassVar[type[NodeConfig]] = NodeConfig

    def __init__(self, config: NodeConfig | dict[str, Any] | None = None) -> None:
        if isinstance(config, NodeConfig):
            self.config = config
        else:
            self.config = self.Config(**(config or {}))


@dataclass(frozen=True)
class SlotSpec:
    name: str
    title: str
    description: str
    effect: Effect


# Order is the pipeline order.
SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec("parse", "Parse", "Turn files into text, keeping page numbers and tables.", "rebuild"),
    SlotSpec("chunk", "Chunk", "Split documents into retrievable pieces.", "rebuild"),
    SlotSpec("embed", "Embed", "Turn each chunk into a vector.", "rebuild"),
    SlotSpec("vector_store", "Vector store", "Where vectors live and how they are searched.", "rebuild"),
    SlotSpec("retrieve", "Retrieve", "Find the chunks most relevant to a question.", "instant"),
    SlotSpec("rerank", "Rerank", "Re-score the top results with a slower, sharper model.", "instant"),
    SlotSpec("prompt", "Prompt", "How retrieved chunks are presented to the model.", "instant"),
    SlotSpec("generate", "Generate", "The language model that writes the answer.", "instant"),
)
SLOT_BY_NAME = {s.name: s for s in SLOTS}


@dataclass
class NodeSpec:
    slot: str
    type: str
    cls: type[Node]
    title: str
    description: str
    # Vector stores: whether search is exact (deterministic) or approximate.
    # Stores whose exactness depends on config override `is_exact`.
    exact: bool | None = None
    availability: Callable[[], tuple[bool, str]] | None = None

    def available(self) -> tuple[bool, str]:
        return self.availability() if self.availability else (True, "")


_REGISTRY: dict[str, dict[str, NodeSpec]] = {s.name: {} for s in SLOTS}


def register(
    slot: str,
    type_: str,
    *,
    title: str,
    description: str = "",
    exact: bool | None = None,
    availability: Callable[[], tuple[bool, str]] | None = None,
) -> Callable[[type[Node]], type[Node]]:
    if slot not in _REGISTRY:
        raise ValueError(f"unknown slot {slot!r}")

    def deco(cls: type[Node]) -> type[Node]:
        if type_ in _REGISTRY[slot]:
            raise ValueError(f"duplicate node type {slot}.{type_}")
        cls.slot = slot
        cls.type = type_
        _REGISTRY[slot][type_] = NodeSpec(
            slot=slot,
            type=type_,
            cls=cls,
            title=title,
            description=description or (cls.__doc__ or "").strip().split("\n")[0],
            exact=exact,
            availability=availability,
        )
        return cls

    return deco


def get_spec(slot: str, type_: str) -> NodeSpec:
    try:
        return _REGISTRY[slot][type_]
    except KeyError:
        raise KeyError(f"unknown node type {slot}.{type_}") from None


def slot_types(slot: str) -> dict[str, NodeSpec]:
    return _REGISTRY[slot]


def build_node(slot: str, cfg: dict[str, Any]) -> Node:
    params = {k: v for k, v in cfg.items() if k != "type"}
    return get_spec(slot, cfg["type"]).cls(params)


def field_effects(slot: str, config_cls: type[NodeConfig]) -> dict[str, Effect]:
    default = SLOT_BY_NAME[slot].effect
    out: dict[str, Effect] = {}
    for name, f in config_cls.model_fields.items():
        extra = f.json_schema_extra if isinstance(f.json_schema_extra, dict) else {}
        out[name] = extra.get("effect", default)  # type: ignore[assignment]
    return out
