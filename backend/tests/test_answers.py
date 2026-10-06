import json
import math
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


def _fakes(monkeypatch, calls=None):
    calls = [] if calls is None else calls

    async def fake_answer(cfg, question, final):
        return {"answer": "Three times [1]." if "retried" in question else "No limit [1].", "sources": ["s"]}

    async def fake_complete(provider, opts, system, user):
        assert system == evaluate.GRADE_SYSTEM and opts["temperature"] == 0
        calls.append(provider)
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
    assert results["i1"]["correct"] == "yes" and results["i1"]["answer"] == "Three times [1]."
    # the limit passage reached the prompt but the answer was wrong -> mode 4
    assert results["i2"]["in_context"] and results["i2"]["diagnosis"] == "failed_to_extract"
    assert m["diagnoses"]["failed_to_extract"] == 1


async def test_auto_optimize_grades_only_top_cells(project, monkeypatch):  # noqa: F811
    base = _cfg("numpy")
    v = await _version(base)
    await _one_item_set(project)
    calls = []
    _fakes(monkeypatch, calls)
    cells = sweep.expand_grid(base, [{"path": "retrieve.top_k", "values": [1, 2, 3, 5, 8]}])
    async with db.tx() as c:
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, created_at)"
                        " VALUES ('sw', 'p', 's', ?, '[]', ?, ?)", (v["id"], db.dumps(cells), db.now_iso()))
    await sweep.run_sweep(Job(id="j", kind="sweep", project_id="p"), "sw", auto_optimize=True,
                          judge={"provider": "gemini", "model": "judge"})
    cells = db.loads((await db.fetch_one("SELECT cells FROM sweeps WHERE id='sw'"))["cells"])
    graded = [c for c in cells if "answers" in c["metrics"]]
    assert len(graded) == 2  # ceil(5 * 0.25)
    assert sorted(str(c["overrides"]) for c in graded) == sorted(str(c["overrides"]) for c in sweep.to_grade(cells))
    # both graded cells score 50% -> overlapping intervals -> each re-judged twice more (median-of-3)
    assert all(c["metrics"]["answers"].get("rejudged") for c in graded)
    assert calls == ["gemini"] * 6  # 2 cells x (1 grading + 2 re-judgings), one batch each


# --- modes 5-7, judge choice, median-of-3 -------------------------------------------------


def test_format_problem_checks_the_citation_contract():
    assert evaluate.format_problem("It retries three times [1].", 2) is None
    assert evaluate.format_problem("It retries three times [1, 2][2].", 2) is None
    assert evaluate.format_problem("It retries three times.", 2) == "no [n] citations"
    assert evaluate.format_problem("I don't know based on these sources.", 2) is None
    assert evaluate.format_problem("Three times [3].", 2).startswith("cites [3]")
    assert evaluate.format_problem("Three times.", 0) is None  # nothing to cite


def test_diagnose_answer_one_mode_most_upstream_first():
    base = {"in_context": True, "diagnosis": None, "correct": "no"}
    cases = [
        ({}, "failed_to_extract"),
        ({"specificity": "too_vague"}, "wrong_specificity"),
        ({"specificity": "too_vague", "missing_facts": ["3 retries"]}, "incomplete_answer"),
        ({"missing_facts": ["3 retries"], "format_error": "no [n] citations"}, "incorrect_format"),
        ({"correct": "partial", "missing_facts": ["x"]}, "incomplete_answer"),
        ({"correct": "yes", "format_error": "no [n] citations"}, None),          # not a failure
        ({"in_context": False, "missing_facts": ["x"]}, None),                    # retrieval's problem
        ({"diagnosis": "ranked_below_k", "missing_facts": ["x"]}, "ranked_below_k"),  # upstream wins
        ({"diagnosis": "incomplete_answer", "correct": "yes"}, None),             # re-judged to correct
    ]
    for extra, want in cases:
        r = {**base, **extra}
        evaluate.diagnose_answer(r)
        assert r["diagnosis"] == want, (extra, r["diagnosis"])


def test_median_verdict_and_near_leader():
    assert evaluate.median_verdict(["yes", "no", "partial"]) == "partial"
    assert evaluate.median_verdict(["yes", "no", "yes"]) == "yes"
    assert evaluate.median_verdict([None, "no"]) == "no" and evaluate.median_verdict([None]) is None

    def cell(rate, k, n=20):
        return {"metrics": {"answers": {"n": n, "correct_rate": rate, "correct_ci": list(M.wilson(k, n))}}}

    lead, close, far = cell(0.9, 18), cell(0.8, 16), cell(0.2, 4)
    assert sweep.near_leader([far, close, lead]) == [lead, close]
    assert sweep.near_leader([lead, far]) == []  # clear winner: no re-judging
    assert sweep.near_leader([lead, {"metrics": {}}]) == []


def test_ndcg_at_k():
    m = M.summarize([1, 3, None, 9], k=5)
    assert m["ndcg_at_k"] == pytest.approx((1 + 1 / math.log2(4)) / 4, abs=1e-4)  # rank 9 > k counts 0


async def test_grading_reports_facets_specificity_relevancy_and_uses_the_judge(project, monkeypatch):  # noqa: F811
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _one_item_set(project)
    async with db.tx() as c:
        await c.execute("UPDATE eval_items SET facets=? WHERE id='i1'", (db.dumps(["three times", "backoff"]),))
    seen = {}

    async def fake_answer(cfg, question, final):
        return {"answer": "It retries [1]." if "retried" in question else "Uploads are limited.", "sources": ["a", "b"]}

    async def fake_complete(provider, opts, system, user):
        seen.update(provider=provider, model=opts["model"], temperature=opts["temperature"])
        assert "Required facts:\n  1. three times\n  2. backoff" in user
        return json.dumps({"results": [
            {"id": 1, "correct": "partial", "grounded": "yes", "relevant": "yes", "specificity": "ok",
             "facts": ["no", "yes"]},
            {"id": 2, "correct": "no", "grounded": "yes", "relevant": "partial", "specificity": "too_vague"}]})

    monkeypatch.setattr(evaluate, "generate_answer", fake_answer)
    monkeypatch.setattr(evaluate, "complete", fake_complete)
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES ('r', 's', 'p', ?, ?)", (v["id"], db.now_iso()))
    await evaluate.run_eval(Job(id="j", kind="eval", project_id="p"), "r", "p", "s", v, answers=True,
                            judge={"provider": "nvidia", "model": "judge-model"})
    run = await db.fetch_one("SELECT * FROM eval_runs WHERE id='r'")
    m, res = db.loads(run["metrics"]), {r["item_id"]: r for r in db.loads(run["results"])}
    assert seen == {"provider": "nvidia", "model": "judge-model", "temperature": 0}
    assert m["answers"]["judge"] == "nvidia/judge-model" and m["answers"]["relevant_rate"] == 0.5
    assert res["i1"]["missing_facts"] == ["three times"] and res["i1"]["diagnosis"] == "incomplete_answer"
    # i2 has no citations at all: the format check (mode 5) wins over the judged specificity
    assert res["i2"]["format_error"] == "no [n] citations" and res["i2"]["diagnosis"] == "incorrect_format"
    assert res["i2"]["specificity"] == "too_vague" and res["i2"]["relevant"] == "partial"
    assert m["diagnoses"]["incomplete_answer"] == 1 and m["diagnoses"]["incorrect_format"] == 1
    assert "p95_ms" in m and "ndcg_at_k" in m and run["set_revision"] == 0
