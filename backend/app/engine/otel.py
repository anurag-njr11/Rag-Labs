"""OpenTelemetry trace ingestion for external systems (PRD FR-4.7).

Each eval question sent to an external RAG carries `traceparent: 00-<trace id>-...` (engine/external.py). A system
instrumented with OpenTelemetry keeps that trace id on its spans; pointed at RAGLabs
(`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:8000/api/otel/v1/traces`), its exporter sends them here.
Spans are joined to eval results by trace id when a run is read, so spans that arrive after the run finished
(exporters batch) still show up. Token counts come from the GenAI semantic conventions
(`gen_ai.usage.input_tokens` / `output_tokens`, plus the older and OpenInference names); cost from our price list
when `gen_ai.request.model` is a model we know.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from .. import db
from ..core import evalmetrics as M
from ..llm import provider as llm

MAX_SPANS = 1000  # per request
MAX_PER_TRACE = 100  # steps shown per question
KEEP_DAYS = 30  # ponytail: age-based pruning; keep spans of runs still in the database if that matters

IN_KEYS = ("gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt")
OUT_KEYS = ("gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.token_count.completion")
MODEL_KEYS = ("gen_ai.request.model", "gen_ai.response.model", "llm.model_name")


class OtelError(ValueError):
    pass


def _value(v: dict[str, Any]) -> Any:
    """An OTLP JSON AnyValue -> a plain value (arrays/maps are kept as JSON-ish structures)."""
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        return int(v["intValue"])  # JSON encodes int64 as a string
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _value(kv.get("value", {})) for kv in v["kvlistValue"].get("values", [])}
    return None


def _from_json(body: dict[str, Any]) -> list[dict[str, Any]]:
    spans = []
    for rs in body.get("resourceSpans") or []:
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
            for s in ss.get("spans") or []:
                spans.append({
                    "trace_id": str(s.get("traceId", "")).lower(), "span_id": str(s.get("spanId", "")).lower(),
                    "parent_id": str(s.get("parentSpanId", "") or "").lower(), "name": str(s.get("name", "")),
                    "start_ns": int(s.get("startTimeUnixNano", 0)), "end_ns": int(s.get("endTimeUnixNano", 0)),
                    "attrs": {a["key"]: _value(a.get("value", {})) for a in s.get("attributes") or []},
                })
    return spans


def _from_protobuf(raw: bytes) -> list[dict[str, Any]]:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    req = ExportTraceServiceRequest()
    try:
        req.ParseFromString(raw)
    except Exception as e:  # DecodeError
        raise OtelError("Not an OTLP protobuf trace export.") from e
    spans = []
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            for s in ss.spans:
                spans.append({
                    "trace_id": s.trace_id.hex(), "span_id": s.span_id.hex(), "parent_id": s.parent_span_id.hex(),
                    "name": s.name, "start_ns": s.start_time_unix_nano, "end_ns": s.end_time_unix_nano,
                    "attrs": {a.key: _value(MessageToDict(a.value)) for a in s.attributes},
                })
    return spans


def parse(raw: bytes, content_type: str, encoding: str = "") -> list[dict[str, Any]]:
    if encoding.lower() == "gzip":
        raw = gzip.decompress(raw)
    if "json" in content_type:
        try:
            body = json.loads(raw)
        except ValueError as e:
            raise OtelError("The body isn't JSON.") from e
        spans = _from_json(body if isinstance(body, dict) else {})
    else:
        spans = _from_protobuf(raw)
    spans = [s for s in spans if len(s["trace_id"]) == 32 and s["end_ns"] >= s["start_ns"] > 0]
    if len(spans) > MAX_SPANS:
        raise OtelError(f"At most {MAX_SPANS} spans per export.")
    return spans


async def store(spans: list[dict[str, Any]]) -> int:
    async with db.tx() as c:
        await c.execute("DELETE FROM external_spans WHERE received_at < datetime('now', ?)", (f"-{KEEP_DAYS} days",))
        await c.executemany(
            "INSERT OR REPLACE INTO external_spans (trace_id, span_id, parent_id, name, start_ns, end_ns, attrs,"
            " received_at) VALUES (?,?,?,?,?,?,?, datetime('now'))",
            [(s["trace_id"], s["span_id"], s["parent_id"], s["name"], s["start_ns"], s["end_ns"],
              db.dumps(s["attrs"])) for s in spans])
    return len(spans)


def _int(v: Any) -> int:
    """A token count from an untrusted attribute: anything that isn't a non-negative number counts as 0."""
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _first(attrs: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return next((attrs[k] for k in keys if attrs.get(k) not in (None, "")), None)


def _price(model: str | None, tokens_in: int, tokens_out: int) -> float | None:
    if not model:
        return None
    for (prov, m), price in llm.PRICES.items():
        if m == model and price is not None:
            return llm.cost_usd(prov, m, tokens_in, tokens_out)
    return None


def to_steps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One trace's spans -> steps shaped like our own trace steps (`start_ms` relative to the first span)."""
    rows = sorted(rows, key=lambda r: (r["start_ns"], r["name"]))[:MAX_PER_TRACE]
    t0 = rows[0]["start_ns"] if rows else 0
    # A system that honours our traceparent parents its top span on *our* span, which is never exported:
    # a root is a span whose parent isn't in the trace.
    ids = {r["span_id"] for r in rows}
    steps = []
    for i, r in enumerate(rows):
        attrs = db.loads(r["attrs"], {}) or {}
        tin, tout = _int(_first(attrs, IN_KEYS)), _int(_first(attrs, OUT_KEYS))
        model = _first(attrs, MODEL_KEYS)
        cost = _price(str(model) if model else None, tin, tout)
        steps.append({
            "seq": i, "step": r["name"], "start_ms": round((r["start_ns"] - t0) / 1e6, 1),
            "ms": round((r["end_ns"] - r["start_ns"]) / 1e6, 1), "tokens_in": tin, "tokens_out": tout,
            "cost_usd": cost or 0.0, "root": r["parent_id"] not in ids,
            "payload": {"model": model, "priced": cost is not None} if (tin or tout or model) else {},
        })
    return steps


async def steps_for(trace_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    ids = [t for t in trace_ids if t]
    if not ids:
        return {}
    rows = await db.fetch_all(
        f"SELECT * FROM external_spans WHERE trace_id IN ({','.join('?' * len(ids))})", tuple(ids))
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["trace_id"], []).append(r)
    return {t: to_steps(rs) for t, rs in by.items()}


def summary(per_item: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Per step name across questions: p50/p95 ms, mean tokens, in the order steps typically start. Root spans (the
    whole request) are left out, so the list says where the time inside the system goes."""
    by: dict[str, list[dict[str, Any]]] = {}
    for steps in per_item:
        for s in steps:
            if not s["root"]:
                by.setdefault(s["step"], []).append(s)
    rows = [{"step": name, "n": len(ss), "start_ms": round(M.percentile([s["start_ms"] for s in ss], 0.5), 1),
             "p50_ms": round(M.percentile([s["ms"] for s in ss], 0.5), 1),
             "p95_ms": round(M.percentile([s["ms"] for s in ss], 0.95), 1),
             "tokens_in": round(sum(s["tokens_in"] for s in ss) / len(ss)),
             "tokens_out": round(sum(s["tokens_out"] for s in ss) / len(ss))} for name, ss in by.items()]
    return sorted(rows, key=lambda r: r["start_ms"])
