"""Agentic retrieval (FR-3.1) and context offloading (FR-3.2)."""

import json
import re

import pytest

from app.core.node import RunContext
from app.core.pipeline import validate_pipeline
from app.engine import agentic, evaluate, retrieval
from app.ingest import builder
from app.nodes import generate as G
from test_eval import project  # noqa: F401  (fixture)
from test_retrieval import _cfg

Q = "How many times are failed uploads retried, and what is the upload size limit?"


def _agentic(**kw):
    cfg = _cfg("numpy")
    return validate_pipeline({**cfg, "retrieve": {**cfg["retrieve"], "type": "agentic", "top_k": 4, **kw}})


@pytest.fixture
def planner(monkeypatch):
    """Scripted planner: replies in order; records each prompt."""
    monkeypatch.setattr(agentic, "_runs", {})
    state = {"replies": [], "prompts": []}

    async def complete(self, prompt, max_tokens):
        state["prompts"].append(prompt)
        return state["replies"].pop(0), 100, 20

    monkeypatch.setattr(G.ProviderGenerator, "complete", complete)
    return state


def _alias(prompt, needle):
    """The planner's alias for the passage whose view contains `needle`."""
    for block in re.split(r"\n(?=\[c\d+\] )", prompt):
        m = re.match(r"\[(c\d+)\] ", block)
        if m and needle.lower() in block.lower():
            return m.group(1)
    raise AssertionError(f"{needle!r} not shown to the planner:\n{prompt}")


async def test_plan_search_keep(project, planner):  # noqa: F811
    cfg = _agentic()
    build = await builder.sync_build(project, cfg)
    planner["replies"] = [json.dumps({"action": "search", "queries": ["upload size limit", Q]})]
    ctx = RunContext()

    async def second():  # the done step names passages by alias, so script it from what it was shown
        prompt = planner["prompts"][-1]
        return json.dumps({"action": "done", "keep": [_alias(prompt, "250 megabytes"), _alias(prompt, "three times"), "c99"]})

    orig = G.ProviderGenerator.complete

    async def complete(self, prompt, max_tokens):
        if planner["replies"]:
            return await orig(self, prompt, max_tokens)
        planner["prompts"].append(prompt)
        return await second(), 100, 20

    G.ProviderGenerator.complete = complete
    try:
        res = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=Q)
    finally:
        G.ProviderGenerator.complete = orig
    agent = [e for e in ctx.events if e.step == "agent"]
    assert [e.payload["action"] for e in agent] == ["search", "done"]
    assert agent[0].payload["queries"] == ["upload size limit"]  # the repeat of the question is dropped
    assert agent[1].payload["keep"] == 2  # the invented alias is ignored
    assert "250 megabytes" in res[0]["text"] and "three times" in res[1]["text"]
    assert len(res) == 4 and [r["rank"] for r in res] == [1, 2, 3, 4]
    assert sum(e.step == "keyword_search" for e in ctx.events) == 2  # question + one new query
    assert all(e.tokens_in == 100 for e in agent)

    # Cached: same question → no planner call, cost still reported at the uncached price.
    ctx2 = RunContext()
    again = await retrieval.retrieve(ctx2, build=build, cfg={**cfg, "retrieve": {**cfg["retrieve"], "top_k": 2}},
                                     question=Q)
    assert [r["id"] for r in again] == [r["id"] for r in res[:2]]
    (ev,) = [e for e in ctx2.events if e.step == "agent"]
    assert ev.payload["cached"] and "uncached_cost_usd" in ev.payload and ev.payload["uncached_ms"] > 0


async def test_offload_shows_snippets_and_reads(project, planner):  # noqa: F811
    cfg = _agentic(offload=True, max_steps=2)
    build = await builder.sync_build(project, cfg)
    planner["replies"] = [json.dumps({"action": "read", "ids": ["c1", "c42"]}), "not json at all"]
    ctx = RunContext()
    res = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=Q)
    first, second = planner["prompts"]
    assert '"action": "read"' in first and "snippets" in first
    # c1 was read: its full text is in the next prompt, longer than its snippet was
    c1_before = next(b for b in re.split(r"\n(?=\[c\d+\] )", first) if b.startswith("[c1] "))
    c1_after = next(b for b in re.split(r"\n(?=\[c\d+\] )", second) if b.startswith("[c1] "))
    assert len(c1_after) > len(c1_before)
    agent = [e for e in ctx.events if e.step == "agent"]
    assert agent[0].payload["read"] == 1 and agent[1].payload.get("invalid_reply")
    assert res  # an unusable reply still returns what the searches found


async def test_offload_keeps_planner_context_smaller(project, planner):  # noqa: F811
    sizes = {}
    for offload in (False, True):
        cfg = _agentic(offload=offload, max_steps=1)
        build = await builder.sync_build(project, cfg)
        planner["replies"] = [json.dumps({"action": "done", "keep": []})]
        ctx = RunContext()
        await retrieval.retrieve(ctx, build=build, cfg=cfg, question=Q)
        sizes[offload] = next(e for e in ctx.events if e.step == "agent").payload["context_chars"]
    assert sizes[True] < sizes[False]


async def test_eval_scores_agentic_and_counts_planner_cost(project, planner):  # noqa: F811
    cfg = _agentic(max_steps=1)
    build = await builder.sync_build(project, cfg)
    planner["replies"] = [json.dumps({"action": "done", "keep": []})]
    item = {"id": "i", "question": "how many times are failed uploads retried", "document_id": "x", "evidence": "x"}
    r = await evaluate.score_item(build, cfg, evaluate.deep_config(cfg), item)
    assert r["diagnosis"] == "not_retrieved" and not planner["replies"]  # the deep pass reused the cached run
    assert r["llm_tokens"] == 120 and r["cost_usd"] is not None  # one planner call: 100 in + 20 out
