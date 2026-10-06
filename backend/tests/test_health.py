import json
import re

import numpy as np

from app import db
from app.engine import evaluate, health
from app.ingest import builder
from app.ingest.documents import create_document
from app.ingest.jobs import Job
from test_eval import LONG_DOCS, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def test_cluster_groups_similar_and_is_deterministic():
    v = np.array([[1, 0, 0], [0.95, 0.05, 0], [0, 1, 0], [0.9, 0.1, 0], [0, 0.97, 0.03]], dtype=np.float32)
    assert health.cluster(v, 0.9) == [[0, 1, 3], [2, 4]]
    assert health.cluster(v, 0.9) == health.cluster(v, 0.9)
    assert health.cluster(np.zeros((0, 3))) == []


def test_similar_pairs_cross_document_only():
    v = np.array([[1, 0], [1, 0], [1, 0.01], [0, 1]], dtype=np.float32)
    pairs = health.similar_pairs(v, ["a", "a", "b", "b"], threshold=0.9, limit=10)
    # 0-1 share a document; 3 is orthogonal; so only 0-2 and 1-2, i < j, most similar first
    assert [(i, j) for i, j, _ in pairs] == [(0, 2), (1, 2)]
    assert health.similar_pairs(v, ["a", "a", "b", "b"], threshold=0.9, limit=1) == pairs[:1]


def test_coverage_summary():
    s = health.coverage_summary(["covered", "missing", "partial", "covered"])
    assert s == {"n": 4, "covered": 2, "partial": 1, "missing": 1, "covered_rate": 0.5}
    assert health.coverage_summary([])["covered_rate"] == 0.0


async def test_report_end_to_end(project, monkeypatch):  # noqa: F811
    # a near-copy of uploads.md in another document -> duplicate content
    await create_document("p", "uploads-copy.md", (LONG_DOCS["uploads.md"] + "\nCopied.").encode())
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    async with db.tx() as c:
        for i, q in enumerate(["how many times are failed uploads retried", "how do I export invoices to csv",
                               "How many times are failed uploads retried?"]):  # last = duplicate of the first
            await c.execute("INSERT INTO runs (id, project_id, question, status, created_at) VALUES (?, 'p', ?, 'ok', ?)",
                            (f"run{i}", q, f"2026-01-0{i + 1}"))
        await c.execute("INSERT INTO corpus_reports (id, project_id, version_id, created_at) VALUES ('r', 'p', ?, ?)",
                        (v["id"], db.now_iso()))

    async def fake_complete(provider, opts, system, user):
        if system == health.JUDGE_SYSTEM:
            qs = re.findall(r"### Question (\d+): (.*)", user)
            return json.dumps({"results": [
                {"id": int(n), "verdict": "missing" if ("export" in q or "SSO" in q) else "covered",
                 "missing": "invoice export guide" if "export" in q else "SSO setup"} for n, q in qs]})
        pairs = re.findall(r"### Pair (\d+)", user)
        return json.dumps({"results": [{"id": int(n), "contradiction": True, "explanation": "x"} for n in pairs]})

    monkeypatch.setattr(evaluate, "complete", fake_complete)
    result = await health.run_report(Job(id="j", kind="health", project_id="p"), "r", "p", v,
                                     ["Can I configure SSO?", "how do I export invoices to CSV?"])
    # 2 pasted + 1 history: the history export question and the retry repeat normalise to ones already seen
    assert result["questions"] == 3
    row = await db.fetch_one("SELECT * FROM corpus_reports WHERE id='r'")
    r = db.loads(row["result"])
    assert row["status"] == "ready"
    s = r["coverage"]["summary"]
    assert (s["n"], s["covered"], s["missing"]) == (3, 1, 2)
    assert s["sources"] == {"pasted": 2, "history": 1}
    assert {t["topic"] for t in r["coverage"]["topics"]} == {"invoice export guide", "SSO setup"}
    assert any({d["a"]["document"], d["b"]["document"]} == {"uploads.md", "uploads-copy.md"} for d in r["duplicates"])
    assert r["usage"]["questions"] == 3 and r["usage"]["chunks_used"] >= 1
    md = health.to_markdown({**row, "result": r, "version": 1}, "P")
    assert "## Content backlog" in md and "invoice export guide" in md
