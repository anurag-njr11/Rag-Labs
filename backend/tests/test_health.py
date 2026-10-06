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


# --- FR-2.30 OKF metadata, FR-2.28 staleness, retrieval-miss labelling ---------------------------

def test_front_matter_okf_fields():
    from app.ingest.documents import front_matter, okf_from_front_matter

    md = ("﻿---\r\ntitle: Uploads\r\nstatus: Deprecated\r\nstale_after: '2025-01-31'\r\nverified: 2024-06-01\r\n"
          "sources:\r\n  - https://a.example\r\n  - \"ticket 42\"\r\nusage_count: 9\r\n---\r\n# Body\n")
    assert front_matter(md)["title"] == "Uploads"
    assert okf_from_front_matter(md.encode()) == {  # usage_count is computed, never read from the file
        "status": "Deprecated", "stale_after": "2025-01-31", "verified": "2024-06-01",
        "sources": ["https://a.example", "ticket 42"]}
    # inline list, bool, a bad date is dropped without losing the rest
    assert okf_from_front_matter(b"---\nsources: [x, 'y']\nverified: true\nstale_after: soon\n---\n") == {
        "sources": ["x", "y"], "verified": True}
    assert okf_from_front_matter(b"---\nsources: https://one\n---\n") == {"sources": ["https://one"]}
    assert okf_from_front_matter(b"# No front matter\nstatus: draft\n") == {}
    assert okf_from_front_matter(b"---\nstatus: draft\n") == {}  # unterminated


def test_staleness_reasons_and_order():
    from datetime import date

    docs = [
        {"id": "a", "filename": "a.md", "okf": {"status": "deprecated"}, "last_modified": None},
        {"id": "b", "filename": "b.md", "okf": {"stale_after": "2026-01-01"}, "last_modified": "2026-05-01T00:00:00+00:00"},
        {"id": "c", "filename": "c.md", "okf": {}, "last_modified": "2024-01-01T10:00:00+00:00"},
        {"id": "d", "filename": "d.md", "okf": {"stale_after": "2027-01-01", "status": "published"},
         "last_modified": "2026-09-01T00:00:00+00:00"},
    ]
    out = health.staleness(docs, date(2026, 10, 6), max_age_days=365)
    assert [(r["document"], r["reasons"]) for r in out] == [
        ("c.md", ["old"]), ("b.md", ["past_stale_after"]), ("a.md", ["deprecated"])]
    assert out[0]["age_days"] == 1009
    # a looser threshold drops the old one; the explicit markers still count
    assert [r["document"] for r in health.staleness(docs, date(2026, 10, 6), max_age_days=2000)] == ["b.md", "a.md"]


async def test_document_metadata_api(project):  # noqa: F811
    import httpx

    from app.ingest import jobs
    from app.main import app

    base = "/api/projects/p/documents"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post(f"{base}?build=false", data={"last_modified": ["1700000000000", "0"]}, files=[
            ("files", ("faq.md", b"---\nstatus: draft\nsources: [https://x]\n---\n# FAQ\n\nAnswers.\n", "text/markdown")),
            ("files", ("notes.txt", b"plain notes", "text/plain"))])
        assert r.status_code == 201 and len(r.json()["created"]) == 2
        docs = {d["filename"]: d for d in (await client.get(base)).json()}
        faq = docs["faq.md"]
        assert faq["last_modified"] == "2023-11-14T22:13:20+00:00"
        assert faq["okf"] == {"status": "draft", "sources": ["https://x"], "usage_count": 0}
        assert docs["notes.txt"]["last_modified"] is None and docs["uploads.md"]["okf"] == {"usage_count": 0}

        # usage_count: chunk appearances in recorded runs' retrieval results
        async with db.tx() as c:
            await c.execute("INSERT INTO runs (id, project_id, question, status, result, created_at)"
                            " VALUES ('u1', 'p', 'q', 'ok', ?, ?)",
                            (db.dumps({"retrieved": [{"document_id": faq["id"]}, {"document_id": faq["id"]},
                                                     {"document_id": "other"}]}), db.now_iso()))
        jobs_before = len(jobs.active_for("p"))
        patched = await client.patch(f"{base}/{faq['id']}/metadata",
                                     json={"status": "deprecated", "stale_after": "2026-01-31", "verified": True})
        assert patched.status_code == 200
        assert patched.json()["okf"] == {"status": "deprecated", "stale_after": "2026-01-31", "verified": True,
                                         "usage_count": 2}
        assert patched.json()["last_modified"] == faq["last_modified"]  # edits keep the date
        assert len(jobs.active_for("p")) == jobs_before  # metadata isn't index config: no rebuild
        assert (await client.patch(f"{base}/{faq['id']}/metadata", json={"stale_after": "soon"})).status_code == 422
        assert (await client.patch(f"{base}/nope/metadata", json={})).status_code == 404


async def test_report_labels_retrieval_miss_and_staleness(project, monkeypatch):  # noqa: F811
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    billing = (await db.fetch_one("SELECT id FROM documents WHERE filename='billing.md'"))["id"]
    async with db.tx() as c:
        await c.execute("INSERT INTO document_okf (document_id, metadata, last_modified) VALUES (?, ?, ?)",
                        (billing, db.dumps({"status": "deprecated"}), "2020-01-01T00:00:00+00:00"))
        await c.execute("INSERT INTO corpus_reports (id, project_id, version_id, created_at) VALUES ('r', 'p', ?, ?)",
                        (v["id"], db.now_iso()))

    seen: dict[str, int] = {}

    async def fake_complete(provider, opts, system, user):
        assert system == health.JUDGE_SYSTEM  # no close pairs in this corpus -> no contradiction calls
        out = []
        for n, q in re.findall(r"### Question (\d+): (.*)", user):
            seen[q] = seen.get(q, 0) + 1
            # first pass: both are gaps; deep recheck: the retries question is answered after all
            covered = seen[q] > 1 and "retried" in q
            out.append({"id": int(n), "verdict": "covered" if covered else "missing", "missing": "SSO setup"})
        return json.dumps({"results": out})

    monkeypatch.setattr(evaluate, "complete", fake_complete)
    await health.run_report(Job(id="j", kind="health", project_id="p"), "r", "p", v,
                            ["How many times are failed uploads retried?", "Can I configure SSO?"], stale_days=30)
    row = await db.fetch_one("SELECT * FROM corpus_reports WHERE id='r'")
    r = db.loads(row["result"])
    cov = r["coverage"]
    assert seen == {"How many times are failed uploads retried?": 2, "Can I configure SSO?": 2}  # one recheck each
    assert cov["summary"]["retrieval_miss"] == 1
    assert [m["question"] for m in cov["retrieval_misses"]] == ["How many times are failed uploads retried?"]
    assert [q["question"] for t in cov["topics"] for q in t["questions"]] == ["Can I configure SSO?"]

    stale = r["staleness"]
    assert stale["max_age_days"] == 30 and stale["documents_checked"] == 2 and stale["with_dates"] == 1
    assert [(d["document"], d["reasons"]) for d in stale["documents"]] == [("billing.md", ["deprecated", "old"])]

    md = health.to_markdown({**row, "result": r, "version": 1}, "P")
    assert "## Retrieval misses" in md and "raise `top_k`" in md
    assert "## Stale documents" in md and "**billing.md** — marked deprecated; not modified in over 30 days" in md
    # reports made before staleness existed still export
    assert "## Stale documents" not in health.to_markdown(
        {**row, "result": {k: v for k, v in r.items() if k != "staleness"}, "version": 1}, "P")
