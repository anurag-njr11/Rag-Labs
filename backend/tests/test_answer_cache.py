"""Semantic answer cache (cache slot)."""

import httpx
import numpy as np

from app import db
from app.core.node import get_spec
from app.core.pipeline import validate_pipeline
from app.engine import chat
from app.ingest import builder
from app.nodes import generate as G
from app.nodes.cache import guard_terms
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

Q = "how many times are failed uploads retried"


def test_guard_terms():
    assert guard_terms("top 10 errors") != guard_terms("top 15 errors")
    assert guard_terms("What does `model_dump` do?") == guard_terms("what does model_dump do")
    assert guard_terms("Explain BaseModel.model_validate and fooBar()") == ["basemodel.model_validate", "foobar()"]
    assert guard_terms("how do I reset my password") == []


def _fake_llm(monkeypatch, answer="Three times [1].", finish="stop"):
    calls = []

    async def stream(self, messages, usage):
        calls.append(messages)
        usage.update(tokens_in=50, tokens_out=5, finish_reason=finish)
        yield answer

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    return calls


async def _ask(project, v, q=Q):
    return [ev async for ev in chat.answer(project, v, q)]


async def test_repeat_question_is_served_from_cache(project, monkeypatch):  # noqa: F811
    calls = _fake_llm(monkeypatch)
    cfg = validate_pipeline({**_cfg("numpy"), "cache": {"type": "semantic"}})
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    first = await _ask(project, v)
    assert first[-1]["cache"] is None and len(calls) == 1
    second = await _ask(project, v)
    done = second[-1]
    assert len(calls) == 1  # no model call
    assert done["cache"]["question"] == Q and done["cache"]["similarity"] >= 0.95
    assert done["answer"] == "Three times [1]." and done["citations"] == first[-1]["citations"]
    steps = [s["step"] for s in done["trace"]]
    assert steps == ["cache_lookup"]  # no retrieval, no generation
    run = await db.fetch_one("SELECT result FROM runs WHERE id=?", (done["run_id"],))
    assert db.loads(run["result"])["cache"]["question"] == Q
    assert (await db.fetch_one("SELECT hits FROM answer_cache"))["hits"] == 1


async def test_guard_blocks_different_numbers(project, monkeypatch):  # noqa: F811
    calls = _fake_llm(monkeypatch)
    emb = get_spec("embed", _cfg("numpy")["embed"]["type"]).cls

    real = emb.embed_query

    async def same_vector(self, text):  # every question looks identical to the embedder
        return np.ones_like(await real(self, text))

    cfg = validate_pipeline({**_cfg("numpy"), "cache": {"type": "semantic"}})
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    monkeypatch.setattr(emb, "embed_query", same_vector)
    await _ask(project, v, "what happens after 3 failed uploads")
    done = (await _ask(project, v, "what happens after 5 failed uploads"))[-1]
    assert done["cache"] is None and len(calls) == 2
    (look,) = [s for s in done["trace"] if s["step"] == "cache_lookup"]
    assert look["payload"]["guard_blocked"] and not look["payload"]["hit"]


async def test_document_change_starts_a_fresh_cache_and_truncated_answers_are_not_kept(project, monkeypatch):  # noqa: F811
    from app.ingest.documents import create_document

    calls = _fake_llm(monkeypatch, finish="length")
    cfg = validate_pipeline({**_cfg("numpy"), "cache": {"type": "semantic"}})
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _ask(project, v)
    assert (await db.fetch_one("SELECT COUNT(*) AS n FROM answer_cache"))["n"] == 0  # cut off: not cached
    calls = _fake_llm(monkeypatch)
    await _ask(project, v)
    await create_document(project, "new.md", b"# New\n\nSomething else entirely.")
    await builder.sync_build(project, cfg)
    done = (await _ask(project, v))[-1]
    assert done["cache"] is None and len(calls) == 2  # the corpus changed, so the old answer isn't reused


async def test_cache_api_stats_and_clear(project, monkeypatch):  # noqa: F811
    from app.main import app

    _fake_llm(monkeypatch)
    cfg = validate_pipeline({**_cfg("numpy"), "cache": {"type": "semantic"}})
    await builder.sync_build(project, cfg)
    await _ask(project, await _version(cfg))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await c.get("/api/projects/p/cache")).json() == {"entries": 1, "hits": 0}
        assert (await c.delete("/api/projects/p/cache")).json() == {"cleared": 1}
        assert (await c.get("/api/projects/p/cache")).json() == {"entries": 0, "hits": 0}
        assert (await c.get("/api/projects/nope/cache")).status_code == 404
