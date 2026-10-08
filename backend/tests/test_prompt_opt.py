"""Prompt optimisation (FR-3.11)."""

import json

import httpx
import pytest

from app import db
from app.engine import evaluate
from app.engine import prompt_opt as P
from app.ingest import builder
from app.ingest.jobs import Job
from app.nodes import generate as G
from test_eval import _new_set, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

QA = {f"question number {i} about failed uploads and their retries": f"answer {i} three retries with backoff"
      for i in range(12)}
GOOD = "Answer in one short sentence that states the fact directly."


def test_score_and_split():
    assert P.score("Three retries with backoff [1].", "three retries with backoff", 2) == 1.0
    assert P.score("Three retries with backoff.", "three retries with backoff", 2) == 0.5  # no citation
    assert {P.split(f"id{i}") for i in range(50)} == {"train", "val", "test"}
    assert P.parse_instructions('```json\n{"instructions": ["a", "a", " b  c "]}\n```') == ["a", "b c"]
    assert P.parse_instructions("nope") == []


async def _set_with_items(project):
    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    await _new_set()
    async with db.tx() as c:
        await c.executemany("INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence,"
                            " document_id, gold_chunk_id) VALUES (?, 's', ?, ?, ?, 'x', ?, 'x')",
                            [(f"q{i}", i, q, a, doc["id"]) for i, (q, a) in enumerate(QA.items())])
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")


@pytest.fixture
def scripted(monkeypatch):
    async def stream(self, messages, usage):
        system, user = messages[0]["content"], messages[1]["content"]
        q = user.rsplit("Question: ", 1)[1].strip()
        gold = QA[q]
        yield (f"{gold} [1]." if GOOD in system else
               f"Well, looking at everything in the documentation in a lot of detail, it says {gold} [1].")

    async def complete(provider, opts, system, user):
        assert "Score:" in user and opts["temperature"] == 0.7
        return json.dumps({"instructions": ["Be thorough and explain the background.", GOOD]})

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    monkeypatch.setattr(evaluate, "complete", complete)


async def test_optimiser_picks_the_better_instructions_and_reports_on_test(project, scripted):  # noqa: F811
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _set_with_items(project)
    async with db.tx() as c:
        await c.execute("INSERT INTO prompt_runs (id, project_id, version_id, eval_set_id, created_at)"
                        " VALUES ('pr', 'p', 'v1', 's', ?)", (db.now_iso(),))
    await P.run(Job(id="j", kind="prompt", project_id="p"), "pr", "p", v, "s")
    row = await db.fetch_one("SELECT status, result FROM prompt_runs WHERE id='pr'")
    r = db.loads(row["result"])
    assert row["status"] == "ready" and sum(r["splits"].values()) == 12
    assert r["best"]["extra_instructions"] == GOOD and not r["best"]["is_current"]
    assert r["test"]["after"] == 1.0 > r["test"]["before"] and r["improves"]
    assert any(c["is_current"] for c in r["candidates"]) and len(r["candidates"]) >= 3
    assert r["samples"][0]["after_score"] == 1.0


async def test_too_small_a_set_fails_and_api(project, scripted):  # noqa: F811
    from app.main import app

    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    await _new_set()
    async with db.tx() as c:
        await c.executemany("INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence,"
                            " document_id, gold_chunk_id) VALUES (?, 's', ?, 'q', 'a', 'x', 'd', 'x')",
                            [(f"q{i}", i) for i in range(3)])
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")
        await c.execute("INSERT INTO prompt_runs (id, project_id, created_at) VALUES ('pr', 'p', ?)", (db.now_iso(),))
    with pytest.raises(evaluate.EvalError, match="at least 9"):
        await P.run(Job(id="j", kind="prompt", project_id="p"), "pr", "p", v, "s")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        runs = (await c.get("/api/projects/p/eval/prompt-runs")).json()
        assert runs[0]["status"] == "failed" and "at least 9" in runs[0]["error"]
        assert (await c.get("/api/projects/p/eval/prompt-runs/nope")).status_code == 404
