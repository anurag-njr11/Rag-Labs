"""Chat-to-build (FR-3.25)."""

import json

import httpx
import pytest

from app import db
from app.engine import build_chat as BC
from app.engine import evaluate
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def test_catalog_text_lists_types_fields_and_limits():
    text = BC.catalog_text()
    assert "## retrieve" in text and "- type hybrid" in text and "top_k (integer, min 1, max 50" in text
    assert "query_expansion (one of none|multi_query|hyde|decompose" in text


def test_apply_types_first_and_validates():
    cfg = _cfg("numpy")
    new = BC.apply(cfg, [{"path": "rerank.top_n", "value": 4}, {"path": "rerank.type", "value": "cross_encoder"},
                         {"path": "retrieve.type", "value": "hybrid"}])
    assert new["rerank"]["type"] == "cross_encoder" and new["rerank"]["top_n"] == 4 and new["retrieve"]["type"] == "hybrid"
    with pytest.raises(Exception):
        BC.apply(cfg, [{"path": "retrieve.top_k", "value": 999}])


@pytest.fixture
def model(monkeypatch):
    replies, seen = [], []

    async def complete(provider, opts, system, user):
        assert system == BC.SYSTEM and opts["temperature"] == 0 and "Catalog:" in user
        seen.append(user)
        return replies.pop(0)

    monkeypatch.setattr(evaluate, "complete", complete)
    return replies, seen


async def test_propose_repairs_once_and_reports_the_diff(project, model):  # noqa: F811
    replies, seen = model
    replies += [json.dumps({"changes": [{"path": "retrieve.top_k", "value": 500}], "explanation": "x"}),
                json.dumps({"changes": [{"path": "rerank.type", "value": "cross_encoder"},
                                        {"path": "retrieve.type", "value": "hybrid"}],
                            "explanation": "Hybrid search, then a cross-encoder reranker."})]
    out = await BC.propose(_cfg("numpy"), "add a reranker and switch to hybrid", "gemini", {"model": ""})
    assert out["attempts"] == 2 and "rejected" in seen[1]
    assert {(c["slot"], c["field"]) for c in out["changes"]} == {("rerank", "type"), ("retrieve", "type")}
    assert out["rebuild"] is False and out["config"]["rerank"]["type"] == "cross_encoder"

    replies += ["not json", "still not json"]
    none = await BC.propose(_cfg("numpy"), "make it better", "gemini", {"model": ""})
    assert none["changes"] == [] and none["attempts"] == 1


async def test_build_chat_api(project, model):  # noqa: F811
    from app.main import app

    replies, _ = model
    v = await _version(_cfg("numpy"))
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    replies.append(json.dumps({"changes": [{"path": "chunk.size", "value": 600}], "explanation": "Smaller chunks."}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.post("/api/projects/p/build-chat", json={"instruction": "use 600-character chunks"})
    body = r.json()
    assert r.status_code == 200 and body["rebuild"] is True and body["config"]["chunk"]["size"] == 600
    assert body["changes"][0]["effect"] == "rebuild"
    assert (await db.fetch_one("SELECT COUNT(*) AS n FROM pipeline_versions"))["n"] == 1  # nothing saved
