"""API keys and usage (FR-3.23, self-hosted part; team workspaces belong to the hosted edition — see
OSS_ROADMAP.md).

Security model: the web UI runs on the same machine, so requests from loopback stay open. A request
from anywhere else must carry `Authorization: Bearer rl_…`. A `chat` key may only call its project's
chat endpoint; an `admin` key may call everything. Only the SHA-256 of a key is stored; the key itself
is shown once. A request carrying proxy headers (X-Forwarded-For, Forwarded, X-Real-IP) was relayed, so it is
never treated as local; if your proxy strips them, set `TRUST_LOOPBACK=false` and every request needs a key.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import db
from .config import get_settings

LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_CHAT = re.compile(r"^/api/projects/([^/]+)/chat/?$")
OPEN = {"/api/health"}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def create_key(name: str, scope: str, project_id: str | None) -> dict[str, Any]:
    key = "rl_" + secrets.token_urlsafe(32)
    kid = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO api_keys (id, name, scope, project_id, prefix, key_hash, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", (kid, name, scope, project_id, key[:9], _hash(key), db.now_iso()))
    return {**await get_key(kid), "key": key}  # the only time the key is returned


async def get_key(kid: str) -> dict[str, Any] | None:
    return await db.fetch_one("SELECT id, name, scope, project_id, prefix, created_at, last_used_at, revoked_at"
                              " FROM api_keys WHERE id=?", (kid,))


async def list_keys() -> list[dict[str, Any]]:
    return await db.fetch_all("SELECT id, name, scope, project_id, prefix, created_at, last_used_at, revoked_at"
                              " FROM api_keys ORDER BY created_at DESC")


async def revoke(kid: str) -> bool:
    async with db.tx() as c:
        cur = await c.execute("UPDATE api_keys SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (db.now_iso(), kid))
        return cur.rowcount > 0


async def authenticate(header: str | None) -> dict[str, Any] | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    key = header[7:].strip()
    row = await db.fetch_one("SELECT * FROM api_keys WHERE prefix=? AND revoked_at IS NULL", (key[:9],))
    if row is None or not hmac.compare_digest(row["key_hash"], _hash(key)):
        return None
    async with db.tx() as c:
        await c.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (db.now_iso(), row["id"]))
    return row


def allowed(key: dict[str, Any], method: str, path: str) -> bool:
    if key["scope"] == "admin":
        return True
    m = _CHAT.match(path)
    return method == "POST" and bool(m) and m.group(1) == key["project_id"]


class KeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        s = get_settings()
        local = s.open_access or ((request.client.host if request.client else "") in LOOPBACK and s.trust_loopback
                                  and not any(h in request.headers for h in PROXY_HEADERS))
        request.state.api_key = None
        if path.startswith("/api/") and path not in OPEN and request.method != "OPTIONS":
            header = request.headers.get("authorization")
            key = await authenticate(header) if header else None
            if header and key is None:
                return JSONResponse({"detail": "Invalid or revoked API key."}, status_code=401)
            if key is None and not local:
                return JSONResponse({"detail": "An API key is required: Authorization: Bearer rl_…"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            if key is not None and not allowed(key, request.method, path):
                return JSONResponse({"detail": "This key may only call its project's chat endpoint."}, status_code=403)
            request.state.api_key = key
        return await call_next(request)


async def usage(project_id: str, days: int) -> dict[str, Any]:
    """Per-day chat traffic for the last `days` days, plus totals by source and by API key."""
    since = f"-{days} days"
    daily = await db.fetch_all(
        "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS requests, SUM(status='error') AS errors,"
        " SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out, SUM(cost_usd) AS cost_usd,"
        " SUM(COALESCE(source, 'api') = 'api') AS api"
        " FROM runs WHERE project_id=? AND kind='chat' AND created_at >= datetime('now', ?)"
        " GROUP BY day ORDER BY day", (project_id, since))
    lat = [r["latency_ms"] for r in await db.fetch_all(
        "SELECT latency_ms FROM runs WHERE project_id=? AND kind='chat' AND status='ok'"
        " AND created_at >= datetime('now', ?) ORDER BY latency_ms", (project_id, since))]
    by_key = await db.fetch_all(
        "SELECT k.id, k.name, k.prefix, COUNT(r.id) AS requests FROM runs r JOIN api_keys k ON k.id = r.api_key_id"
        " WHERE r.project_id=? AND r.created_at >= datetime('now', ?) GROUP BY k.id ORDER BY requests DESC",
        (project_id, since))

    def pct(q: float) -> float | None:
        return round(lat[min(len(lat) - 1, int(round(q * (len(lat) - 1))))], 1) if lat else None

    total = {k: sum(d[k] or 0 for d in daily) for k in ("requests", "errors", "tokens_in", "tokens_out", "api")}
    total["cost_usd"] = round(sum(d["cost_usd"] or 0 for d in daily), 6)
    total["playground"] = total["requests"] - total["api"]
    return {"days": days, "daily": daily, "total": total, "latency": {"p50_ms": pct(0.5), "p95_ms": pct(0.95)},
            "by_key": by_key}
