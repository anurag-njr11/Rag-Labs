"""API keys and usage (FR-3.23)."""

import httpx
import pytest

from app import db
from app.config import get_settings
from app.ingest import builder
from app.nodes import generate as G
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def _client(host="203.0.113.5"):
    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(host, 4242)), base_url="http://testserver")


@pytest.fixture
async def ready(project, monkeypatch):  # noqa: F811
    async def stream(self, messages, usage):
        usage.update(tokens_in=40, tokens_out=6)
        yield "Three times [1]."

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
        await c.execute("INSERT INTO projects (id, name, created_at) VALUES ('other', 'O', ?)", (db.now_iso(),))


async def test_remote_callers_need_a_scoped_key(ready):
    ask = {"question": "how many times are failed uploads retried", "stream": False}
    async with _client("127.0.0.1") as local:
        assert (await local.get("/api/projects")).status_code == 200  # the local UI needs no key
        chat_key = (await local.post("/api/keys", json={"name": "website", "project_id": "p"})).json()
        admin_key = (await local.post("/api/keys", json={"name": "ops", "scope": "admin"})).json()
        assert (await local.post("/api/keys", json={"name": "x"})).status_code == 422  # chat key without project
        assert chat_key["key"].startswith("rl_") and "key" not in (await local.get("/api/keys")).json()[0]
    row = await db.fetch_one("SELECT key_hash, prefix FROM api_keys WHERE id=?", (chat_key["id"],))
    assert row["key_hash"] != chat_key["key"] and chat_key["key"].startswith(row["prefix"])

    bearer = lambda k: {"Authorization": f"Bearer {k}"}  # noqa: E731
    async with _client() as remote:
        assert (await remote.get("/api/health")).status_code == 200
        r = await remote.get("/api/projects")
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert (await remote.post("/api/projects/p/chat", json=ask, headers=bearer(chat_key["key"]))).status_code == 200
        assert (await remote.get("/api/projects", headers=bearer(chat_key["key"]))).status_code == 403
        assert (await remote.post("/api/projects/other/chat", json=ask, headers=bearer(chat_key["key"]))).status_code == 403
        assert (await remote.get("/api/projects", headers=bearer(admin_key["key"]))).status_code == 200
        assert (await remote.get("/api/projects", headers=bearer("rl_nope"))).status_code == 401
        # a keyed call is API traffic even if it claims to be the Playground
        await remote.post("/api/projects/p/chat", json=ask, headers={**bearer(chat_key["key"]), "X-RAGLabs-Client": "playground"})
    async with _client("127.0.0.1") as local:
        assert (await local.get("/api/projects", headers=bearer("rl_nope"))).status_code == 401  # bad key, even locally
        assert (await local.delete(f"/api/keys/{chat_key['id']}")).status_code == 204
        assert (await local.delete(f"/api/keys/{chat_key['id']}")).status_code == 404
        usage = (await local.get("/api/projects/p/usage?days=7")).json()
    async with _client() as remote:
        assert (await remote.post("/api/projects/p/chat", json=ask, headers=bearer(chat_key["key"]))).status_code == 401
    runs = await db.fetch_all("SELECT source, api_key_id FROM runs ORDER BY created_at")
    assert [(r["source"], r["api_key_id"]) for r in runs] == [("api", chat_key["id"])] * 2
    assert usage["total"]["requests"] == 2 and usage["total"]["api"] == 2 and usage["total"]["tokens_in"] == 80
    assert usage["by_key"] == [{"id": chat_key["id"], "name": "website", "prefix": chat_key["prefix"], "requests": 2}]
    assert usage["latency"]["p50_ms"] is not None and len(usage["daily"]) == 1


async def test_untrusted_loopback_requires_keys(ready, monkeypatch):
    monkeypatch.setenv("TRUST_LOOPBACK", "false")
    get_settings.cache_clear()
    try:
        async with _client("127.0.0.1") as local:
            assert (await local.get("/api/projects")).status_code == 401
    finally:
        monkeypatch.delenv("TRUST_LOOPBACK")
        get_settings.cache_clear()
