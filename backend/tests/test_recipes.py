"""Recipe gallery (FR-3.26)."""

import httpx

from app import db
from app.engine import recipes
from app.llm import provider as llm
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def _client():
    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def test_builtins_are_valid_and_distinct():
    rs = recipes.builtin()
    assert len({r["id"] for r in rs}) == len(rs) == len(recipes.BUILTIN)
    by = {r["id"]: r["config"] for r in rs}
    assert by["builtin-accurate"]["rerank"]["type"] == "cross_encoder" and by["builtin-accurate"]["retrieve"]["type"] == "hybrid"
    assert by["builtin-agentic"]["retrieve"]["offload"] is True
    assert by["builtin-hardened"]["verify"]["validate_output"] and by["builtin-hardened"]["prompt"]["injection_guard"] == "delimited"


def test_portable_drops_adapter_and_unconnected_llm(monkeypatch):
    cfg = _cfg("numpy")
    cfg["retrieve"]["adapter"] = "abc"
    target = _cfg("numpy")
    monkeypatch.setattr(llm, "availability", lambda name: (False, "no key"))
    out, notes = recipes.portable(cfg, target)
    assert out["retrieve"]["adapter"] == "" and out["generate"] == target["generate"] and len(notes) == 2
    monkeypatch.setattr(llm, "availability", lambda name: (True, ""))
    cfg["retrieve"]["adapter"] = ""
    assert recipes.portable(cfg, target)[1] == []


async def test_save_share_fork_delete(project):  # noqa: F811
    v = await _version(_cfg("numpy"))
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    cfg = {**_cfg("numpy"), "retrieve": {**_cfg("numpy")["retrieve"], "adapter": "secret-adapter", "top_k": 12}}
    async with _client() as c:
        saved = (await c.post("/api/recipes", json={"name": "Our setup", "config": cfg, "source_project": "p"})).json()
        assert saved["config"]["retrieve"]["adapter"] == "" and saved["config"]["retrieve"]["top_k"] == 12
        listed = (await c.get("/api/recipes")).json()
        assert listed[0]["id"] == saved["id"] and any(r["builtin"] for r in listed)
        bad = await c.post("/api/recipes", json={"name": "x", "config": {"retrieve": {"type": "nope"}}})
        assert bad.status_code == 422
        fork = (await c.post("/api/projects/p/recipe-config", json={"config": saved["config"]})).json()
        assert fork["config"]["retrieve"]["top_k"] == 12
        assert (await c.delete("/api/recipes/builtin-fast")).status_code == 409
        assert (await c.delete(f"/api/recipes/{saved['id']}")).status_code == 204
        assert (await c.delete(f"/api/recipes/{saved['id']}")).status_code == 404
        assert (await c.post("/api/projects/nope/recipe-config", json={"config": cfg})).status_code == 404
