"""Cost per 1k queries (list prices), index size, and the contextual precision/recall judges."""

import json
import re

import pytest

from app import db
from app.core import evalmetrics as M
from app.core.node import RunContext
from app.engine import evaluate
from app.ingest import builder
from app.ingest.jobs import Job
from app.llm import provider as llm
from test_answers import _one_item_set
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def test_pricing_math_and_unknown_models():
    # gemini-3.5-flash: $1.50 in / $9.00 out per 1M tokens
    assert llm.cost_usd("gemini", "gemini-3.5-flash", 1_000_000, 100_000) == pytest.approx(2.4)
    assert llm.cost_usd("gemini", "models/gemini-3.5-flash", 2000, 0) == pytest.approx(0.003)
    assert llm.cost_usd("nvidia", "nvidia/nemotron-3-super-120b-a12b", 1000, 1000) is None  # no list price
    assert llm.cost_usd("gemini", "some-new-model", 1000, 1000) is None


def test_unpriced_call_is_flagged_not_zero_cost():
    ctx = RunContext()
    ev = ctx.emit("generate", tokens_in=10, tokens_out=5, cost_usd=None)
    assert ev.cost_usd == 0.0 and ev.payload["priced"] is False
    assert "priced" not in ctx.emit("generate", tokens_in=10, cost_usd=0.01).payload
    assert evaluate.query_cost(ctx.events) is None


def test_query_cost_counts_cached_expansions_at_list_price():
    ctx = RunContext()
    ctx.emit("query_expansion", tokens_in=100, tokens_out=50, cost_usd=0.002)
    ctx.emit("query_expansion", cached=True, uncached_cost_usd=0.003)
    ctx.emit("dense_search", hits=3)
    assert evaluate.query_cost(ctx.events) == pytest.approx(0.005)
    ctx.emit("query_expansion", cached=True, uncached_cost_usd=None)
    assert evaluate.query_cost(ctx.events) is None
    assert M.per_1k([0.001, 0.003]) == pytest.approx(2.0)
    assert M.per_1k([0.001, None]) is None and M.per_1k([]) is None


def test_contextual_precision_formula():
    # relevant at ranks 1 and 3: (1/1 + 2/3) / 2
    assert M.context_precision([True, False, True]) == pytest.approx(0.8333, abs=1e-4)
    assert M.context_precision([False, True]) == 0.5
    assert M.context_precision([True, True]) == 1.0
    assert M.context_precision([False, False]) == 0.0


def test_contextual_recall_with_and_without_facets():
    with_facets = evaluate.contextual({"sources_relevant": ["yes", "no"], "facts_in_sources": ["yes", "no", "yes"]},
                                      n_sources=2, n_facts=3)
    assert with_facets == {"context_precision": 1.0, "context_recall": pytest.approx(0.6667, abs=1e-4)}
    # no facets: the gold answer is the single fact
    assert evaluate.contextual({"sources_relevant": ["no"], "facts_in_sources": ["yes"]}, 1, 1) == \
        {"context_precision": 0.0, "context_recall": 1.0}
    # malformed lists aren't scored; no sources at all scores 0 without asking
    assert evaluate.contextual({"sources_relevant": ["yes"], "facts_in_sources": []}, 2, 1) == \
        {"context_precision": None, "context_recall": None}
    assert evaluate.contextual({}, 0, 2) == {"context_precision": 0.0, "context_recall": 0.0}


async def test_eval_run_reports_cost_index_size_and_contextual_scores(project, monkeypatch):  # noqa: F811
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _one_item_set(project)
    async with db.tx() as c:
        await c.execute("UPDATE eval_items SET facets=? WHERE id='i1'", (db.dumps(["three times", "backoff"]),))

    async def fake_answer(cfg, question, final):
        return {"answer": "Three times [1].", "sources": ["a", "b"], "cost_usd": 0.002}

    async def fake_complete(provider, opts, system, user):
        assert '"sources_relevant"' in system and '"facts_in_sources"' in system
        items = re.findall(r"### Item (\d+)\nQuestion: (.*)", user)
        return json.dumps({"results": [
            {"id": int(n), "correct": "yes", "grounded": "yes",
             # i1 has 2 facets; i2 has none, so the gold answer is its one fact
             "sources_relevant": ["no", "yes"] if "retried" in q else ["yes", "yes"],
             "facts_in_sources": ["yes", "no"] if "retried" in q else ["yes"]} for n, q in items]})

    monkeypatch.setattr(evaluate, "generate_answer", fake_answer)
    monkeypatch.setattr(evaluate, "complete", fake_complete)
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES ('r', 's', 'p', ?, ?)", (v["id"], db.now_iso()))
    await evaluate.run_eval(Job(id="j", kind="eval", project_id="p"), "r", "p", "s", v, answers=True)
    run = await db.fetch_one("SELECT * FROM eval_runs WHERE id='r'")
    m, res = db.loads(run["metrics"]), {r["item_id"]: r for r in db.loads(run["results"])}

    assert m["cost_per_1k"] == 0.0  # retrieval stage: no query expansion, no LLM call
    assert m["answers"]["cost_per_1k"] == pytest.approx(2.0)  # $0.002 per answer
    assert res["i1"]["context_precision"] == 0.5 and res["i1"]["context_recall"] == 0.5
    assert res["i2"]["context_precision"] == 1.0 and res["i2"]["context_recall"] == 1.0
    assert m["answers"]["context_precision"] == 0.75 and m["answers"]["context_recall"] == 0.75

    build = await db.fetch_one("SELECT chunk_count FROM index_builds WHERE id=?", (run["build_id"],))
    assert m["index"]["chunks"] == build["chunk_count"] > 0
    assert m["index"]["vectors"] == m["index"]["chunks"] and m["index"]["bytes"] > 0
