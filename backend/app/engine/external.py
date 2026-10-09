"""Bring your own RAG (PRD §8.7): score a RAG system that runs elsewhere, over HTTP.

Contract: POST <url> {"question": "..."} -> {"answer": "...", "contexts": [{"text", "source", "score"}]}.
`mapping` points at those fields in a different response shape (dotted paths, `contexts.0.text`).
A response without an answer is retrieval-only. Auth headers are stored encrypted (vault).

Each request carries a W3C `traceparent` header, so a system instrumented with OpenTelemetry records its spans
under a trace id we know; exported to RAGLabs (engine/otel.py) they become per-step latency and tokens (FR-4.7).
The same scoring also runs on a Python function in-process (`call`, the `raglabs` SDK), with no server.
"""

from __future__ import annotations

import asyncio
import inspect
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, field_validator

from .. import db, vault


class ExternalError(Exception):
    pass


class ExternalConfig(BaseModel):
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    question_field: str = Field("question", min_length=1, max_length=80)
    answer_path: str = Field("answer", max_length=200)  # "" = retrieval only
    contexts_path: str = Field("contexts", min_length=1, max_length=200)
    text_path: str = Field("text", max_length=200)  # inside one context; "" = the context itself is the text
    source_path: str = Field("source", max_length=200)  # file name/path/URL of the context's document; "" = none
    top_k: int = Field(8, ge=1, le=50)  # contexts scored per question
    timeout_s: float = Field(30, gt=0, le=120)

    @field_validator("url")
    @classmethod
    def _http(cls, v: str) -> str:
        v = v.strip()
        if urlsplit(v).scheme not in ("http", "https") or not urlsplit(v).netloc:
            raise ValueError("must be an http(s) URL")
        if vault.url_has_credentials(v):
            raise ValueError("don't put credentials in the URL; add them as a header")
        return v


def dig(obj: Any, path: str) -> Any:
    """`a.b.0.c` -> obj["a"]["b"][0]["c"]; None if any step is missing."""
    for part in (p for p in path.split(".") if p):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def parse(body: Any, cfg: ExternalConfig) -> dict[str, Any]:
    """A response body -> {answer: str | None, contexts: [{text, external_source, score}]}."""
    raw = dig(body, cfg.contexts_path)
    if not isinstance(raw, list):
        raise ExternalError(f"No list of contexts at '{cfg.contexts_path}' in the response.")
    contexts = []
    for c in raw[: cfg.top_k]:
        text = dig(c, cfg.text_path) if cfg.text_path and isinstance(c, dict) else c
        if not isinstance(text, str):
            raise ExternalError(f"A context has no text at '{cfg.text_path}'.")
        src = dig(c, cfg.source_path) if cfg.source_path and isinstance(c, dict) else None
        score = c.get("score") if isinstance(c, dict) else None
        contexts.append({"text": text, "external_source": str(src) if src else "",
                         "score": score if isinstance(score, (int, float)) else None})
    answer = dig(body, cfg.answer_path) if cfg.answer_path else None
    return {"answer": answer.strip() if isinstance(answer, str) else None, "contexts": contexts}


async def query(cfg: ExternalConfig, question: str) -> dict[str, Any]:
    """One question -> {answer, contexts, ms, trace_id}."""
    trace_id = secrets.token_hex(16)
    headers = {**cfg.headers, "traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01"}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_s, follow_redirects=True) as client:
            r = await client.post(cfg.url, json={cfg.question_field: question}, headers=headers)
    except httpx.HTTPError as e:
        raise ExternalError(vault.redact(f"Couldn't reach {vault.redact_url(cfg.url)}: {e or type(e).__name__}")) from e
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code >= 400:
        raise ExternalError(vault.redact(f"{vault.redact_url(cfg.url)} answered HTTP {r.status_code}: {r.text[:200]}"))
    try:
        body = r.json()
    except ValueError as e:
        raise ExternalError("The response isn't JSON.") from e
    return {**parse(body, cfg), "ms": ms, "trace_id": trace_id}


Ask = Callable[[str], Any]


def shape(out: Any) -> dict[str, Any]:
    """What a Python RAG function returned -> the HTTP contract's body. Accepts the contract dict, a list of
    contexts (retrieval only), or an (answer, contexts) tuple; a context may be a plain string."""
    if isinstance(out, tuple) and len(out) == 2:
        out = {"answer": out[0], "contexts": out[1]}
    elif isinstance(out, list):
        out = {"contexts": out}
    if not isinstance(out, dict):
        raise ExternalError(f"The function returned {type(out).__name__}; return a dict with 'contexts'.")
    return out


async def call(fn: Ask, question: str, top_k: int = 8) -> dict[str, Any]:
    """Score target that runs in this process: `fn(question)`, sync or async."""
    t0 = time.perf_counter()
    try:
        # A sync function runs in a worker thread (as FastAPI runs sync endpoints), so `serve` stays responsive.
        out = await fn(question) if inspect.iscoroutinefunction(fn) else await asyncio.to_thread(fn, question)
        if inspect.isawaitable(out):
            out = await out
    except Exception as e:  # the user's code: any failure is that question's error, not ours
        raise ExternalError(f"The function raised {type(e).__name__}: {e}") from e
    ms = (time.perf_counter() - t0) * 1000
    return {**parse(shape(out), ExternalConfig(url="http://in-process", top_k=top_k)), "ms": ms, "trace_id": None}


# --- storage ---------------------------------------------------------------------------------

def _ctx(system_id: str) -> str:
    return f"external:{system_id}:headers"


async def create(project_id: str, name: str, cfg: ExternalConfig) -> dict[str, Any]:
    sid = db.new_id()
    headers = vault.encrypt(db.dumps(cfg.headers), _ctx(sid)) if cfg.headers else ""
    async with db.tx() as c:
        await c.execute(
            "INSERT INTO external_systems (id, project_id, name, config, headers, created_at) VALUES (?,?,?,?,?,?)",
            (sid, project_id, name, db.dumps(cfg.model_dump(exclude={"headers"})), headers, db.now_iso()))
    return (await get(project_id, sid))  # type: ignore[return-value]


async def get(project_id: str, system_id: str) -> dict[str, Any] | None:
    """The system with its config (headers decrypted, for running) — use `public` before returning it."""
    row = await db.fetch_one("SELECT * FROM external_systems WHERE id=? AND project_id=?", (system_id, project_id))
    if row is None:
        return None
    headers = db.loads(vault.decrypt(row["headers"], _ctx(system_id)), {}) if row["headers"] else {}
    return {**row, "config": ExternalConfig(**db.loads(row["config"], {}), headers=headers)}


def public(system: dict[str, Any]) -> dict[str, Any]:
    cfg: ExternalConfig = system["config"]
    return {"id": system["id"], "name": system["name"], "created_at": system["created_at"],
            "config": {**cfg.model_dump(exclude={"headers"}), "url": vault.redact_url(cfg.url),
                       "header_names": sorted(cfg.headers)}}

