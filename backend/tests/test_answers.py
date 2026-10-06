import json
import re

import pytest

from app import db
from app.core import evalmetrics as M
from app.engine import evaluate, sweep
from app.ingest import builder
from app.ingest.jobs import Job
from test_eval import _new_set, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def test_wilson_interval():
    assert M.wilson(0, 0) == (0.0, 0.0)
    lo, hi = M.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert M.wilson(10, 10)[1] == 1.0 and M.wilson(0, 10)[0] == 0.0


def test_answer_summary_counts_and_ungraded():
    s = M.answer_summary([{"correct": "yes", "grounded": "yes"}, {"correct": "no", "grounded": "partial"},
                          {"correct": "partial", "grounded": "yes"}, {}])
    assert (s["n"], s["ungraded"], s["correct"], s["partial"], s["wrong"]) == (3, 1, 1, 1, 1)
    assert s["correct_rate"] == pytest.approx(1 / 3, abs=1e-3) and s["grounded_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["correct_ci"][0] < s["correct_rate"] < s["correct_ci"][1]


def test_to_grade_takes_top_quarter():
    cells = [{"status": "ready", "metrics": {"mrr": m, "ctx_tokens": t}} for m, t in
             [(0.5, 100), (0.9, 900), (0.9, 300), (0.1, 50), (0.7, 10)]]
    cells.append({"status": "failed"})
    top = sweep.to_grade(cells)
    assert [(c["metrics"]["mrr"], c["metrics"]["ctx_tokens"]) for c in top] == [(0.9, 300), (0.9, 900)]
    assert sweep.to_grade([]) == []


async def _one_item_set(project):
    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    await _new_set()
    async with db.tx() as c:
        await c.executemany(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id) VALUES (?, 's', ?, ?, ?, ?, ?, 'x')",
            [("i1", 0, "how many times are failed uploads retried", "three times",
              "retries failed uploads three times with exponential backoff", doc["id"]),
             ("i2", 1, "what is the upload size limit", "250 megabytes",
              "Each upload is capped at 250 megabytes", doc["id"])])
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")


def _fakes(monkeypatch):
    async def fake_answer(cfg, question, final):
        return {"answer": "Three times." if "retried" in question else "No limit.", "sources": ["s"]}

    async def fake_complete(provider, opts, system, user):
        assert system == evaluate.GRADE_SYSTEM
        items = re.findall(r"### Item (\d+)\nQuestion: (.*)", user)
        return json.dumps({"results": [
            {"id": int(n), "correct": "yes" if "retried" in q else "no", "grounded": "yes"} for n, q in items]})

    monkeypatch.setattr(evaluate, "generate_answer", fake_answer)
    monkeypatch.setattr(evaluate, "complete", fake_complete)


async def test_run_eval_grades_answers_and_flags_failed_extraction(project, monkeypatch):  # noqa: F811
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _one_item_set(project)
    _fakes(monkeypatch)
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES ('r', 's', 'p', ?, ?)", (v["id"], db.now_iso()))
    await evaluate.run_eval(Job(id="j", kind="eval", project_id="p"), "r", "p", "s", v, answers=True)
    run = await db.fetch_one("SELECT * FROM eval_runs WHERE id='r'")
    m, results = db.loads(run["metrics"]), {r["item_id"]: r for r in db.loads(run["results"])}
    assert m["answers"]["n"] == 2 and m["answers"]["correct"] == 1 and m["answers"]["wrong"] == 1
    assert results["i1"]["correct"] == "yes" and results["i1"]["answer"] == "Three times."
    # the limit passage reached the prompt but the answer was wrong -> mode 4
    assert results["i2"]["in_context"] and results["i2"]["diagnosis"] == "failed_to_extract"
    assert m["diagnoses"]["failed_to_extract"] == 1


async def test_auto_optimize_grades_only_top_cells(project, monkeypatch):  # noqa: F811
    base = _cfg("numpy")
    v = await _version(base)
    await _one_item_set(project)
    _fakes(monkeypatch)
    cells = sweep.expand_grid(base, [{"path": "retrieve.top_k", "values": [1, 2, 3, 5, 8]}])
    async with db.tx() as c:
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, created_at)"
                        " VALUES ('sw', 'p', 's', ?, '[]', ?, ?)", (v["id"], db.dumps(cells), db.now_iso()))
    await sweep.run_sweep(Job(id="j", kind="sweep", project_id="p"), "sw", auto_optimize=True)
    cells = db.loads((await db.fetch_one("SELECT cells FROM sweeps WHERE id='sw'"))["cells"])
    graded = [c for c in cells if "answers" in c["metrics"]]
    assert len(graded) == 2  # ceil(5 * 0.25)
    assert sorted(str(c["overrides"]) for c in graded) == sorted(str(c["overrides"]) for c in sweep.to_grade(cells))
