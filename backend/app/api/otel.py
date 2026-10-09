"""OTLP/HTTP trace receiver (FR-4.7): point an external RAG's OpenTelemetry exporter here and its spans show up as
per-step latency and tokens on that system's eval results. Accepts protobuf (the default) and JSON, optionally gzip."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from ..engine import otel

router = APIRouter(tags=["otel"])
MAX_BYTES = 5 * 1024 * 1024


@router.post("/api/otel/v1/traces")
async def export_traces(request: Request) -> Response:
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Trace export too large.")
    ctype = request.headers.get("content-type", "application/x-protobuf")
    try:
        spans = otel.parse(raw, ctype, request.headers.get("content-encoding", ""))
    except (otel.OtelError, OSError) as e:
        raise HTTPException(400, str(e)) from e
    await otel.store(spans)
    # An empty ExportTraceServiceResponse: b"" in protobuf, {} in JSON.
    return Response(b"{}" if "json" in ctype else b"", media_type="application/json" if "json" in ctype
                    else "application/x-protobuf")
