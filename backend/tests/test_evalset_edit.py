import sqlite3

import httpx

from app import db
from app.engine import evaluate
from app.ingest import builder
from app.main import app
from test_eval import _new_set, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

BASE = "/api/projects/p/eval/sets/s"


async def _ready_set():
    build = await builder.sync_build("p", _cfg("numpy"))
    await _version(_cfg("numpy"))
    await _new_set()
    async with db.tx() as c:
        await c.execute("UPDATE eval_sets SET status='ready', build_id=? WHERE id='s'", (build["id"],))
    return (await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'"))["id"]


async def test_hand_edits_and_csv_roundtrip(project):  # noqa: F811
    doc = await _ready_set()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        bad = await client.post(f"{BASE}/items", json={"question": "How big can uploads be?", "gold_answer": "250 MB",
                                                       "evidence": "uploads may be up to one terabyte", "document_id": doc})
        assert bad.status_code == 422 and "wasn't found" in bad.json()["detail"]

        ok = await client.post(f"{BASE}/items", json={
            "question": "How big can uploads be?", "gold_answer": "250 MB",
            "evidence": "Each upload is capped at 250 megabytes", "document_id": doc})
        assert ok.status_code == 201 and ok.json()["valid"] is True
        item = ok.json()["id"]

        dropped = await client.patch(f"{BASE}/items/{item}", json={"valid": False})
        assert dropped.json()["valid"] is False and dropped.json()["reject_reason"] == "removed by hand"
        restored = await client.patch(f"{BASE}/items/{item}", json={"valid": True, "question": "Max upload size?"})
        assert restored.json()["valid"] is True and restored.json()["question"] == "Max upload size?"

        csv_text = (await client.get(f"{BASE}/export.csv")).text
        assert csv_text.splitlines()[0] == "question,gold_answer,evidence,document,valid,reject_reason,facets"
        assert "Max upload size?" in csv_text and "uploads.md" in csv_text

        imported = await client.post(f"{BASE}/import", json={"csv": (
            "question,answer,evidence,document\n"
            "How often are uploads retried?,three times,retries failed uploads three times with exponential backoff,uploads.md\n"
            "Who wrote it?,someone,a sentence that is nowhere at all,uploads.md\n"
            "When are invoices sent?,first business day,Invoices are generated on the first business day,missing.md\n")})
        body = imported.json()
        assert body["added"] == 1 and body["error_count"] == 2
        assert {e["row"] for e in body["errors"]} == {3, 4}

        bad_cols = await client.post(f"{BASE}/import", json={"csv": "q,a\nx,y\n"})
        assert bad_cols.status_code == 422

        assert (await client.delete(f"{BASE}/items/{item}")).status_code == 204
        assert (await client.patch(f"{BASE}/items/{item}", json={"valid": True})).status_code == 404


async def test_csv_formula_escape_cap_and_question_only_edit(project, monkeypatch):  # noqa: F811
    from app.api import eval as eval_api
    doc = await _ready_set()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        q = "=HYPERLINK(1) how big can uploads be?"
        item = (await client.post(f"{BASE}/items", json={"question": q, "gold_answer": "-250 MB",
                                                         "evidence": "Each upload is capped at 250 megabytes",
                                                         "document_id": doc})).json()
        csv_text = (await client.get(f"{BASE}/export.csv")).text
        assert f"'{q}" in csv_text and "'-250 MB" in csv_text  # a spreadsheet shows it as text
        await client.delete(f"{BASE}/items/{item['id']}")
        assert (await client.post(f"{BASE}/import", json={"csv": csv_text})).json()["added"] == 1
        back = (await client.get(BASE)).json()["items"]
        assert [(i["question"], i["gold_answer"]) for i in back] == [(q, "-250 MB")]  # round-trips exactly

        # cap: import stops at MAX_ITEMS valid questions and says how many it skipped
        monkeypatch.setattr(eval_api, "MAX_ITEMS", 2)
        row = "How often are uploads retried?,three,retries failed uploads three times with exponential backoff,uploads.md\n"
        body = (await client.post(f"{BASE}/import", json={"csv": "question,answer,evidence,document\n" + row * 3})).json()
        assert (body["added"], body["skipped"]) == (1, 2)
        full = await client.post(f"{BASE}/items", json={"question": "Max size?", "gold_answer": "250 MB",
                                                         "evidence": "Each upload is capped at 250 megabytes",
                                                         "document_id": doc})
        assert full.status_code == 409

    # a question-only edit of an item whose stored evidence fails the check still saves
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
                        " gold_chunk_id, valid, reject_reason) VALUES ('bad', 's', 9, 'old?', 'a', 'not in the doc', ?,"
                        " 'x', 0, 'evidence not found in source')", (doc,))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.patch(f"{BASE}/items/bad", json={"question": "New wording?", "gold_answer": "a",
                                                          "evidence": "not in the doc", "facets": []})
        assert r.status_code == 200 and r.json()["question"] == "New wording?"


async def test_facets_revision_and_corpus_fingerprint(project):  # noqa: F811
    doc = await _ready_set()
    async with db.tx() as c:
        await c.execute("UPDATE eval_sets SET corpus_sha=? WHERE id='s'", (await evaluate.corpus_sha("p"),))

    async def revision():
        return (await db.fetch_one("SELECT revision FROM eval_sets WHERE id='s'"))["revision"]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get(BASE)).json()["corpus_changed"] is False
        ok = await client.post(f"{BASE}/items", json={
            "question": "How big can uploads be?", "gold_answer": "250 MB", "facets": ["250 MB", " ", "250 mb"],
            "evidence": "Each upload is capped at 250 megabytes", "document_id": doc})
        item = ok.json()
        assert item["facets"] == ["250 MB"] and await revision() == 1
        patched = await client.patch(f"{BASE}/items/{item['id']}", json={"facets": ["250 MB", "rejected"]})
        assert patched.json()["facets"] == ["250 MB", "rejected"] and await revision() == 2

        csv_text = (await client.get(f"{BASE}/export.csv")).text
        assert "250 MB | rejected" in csv_text
        imported = await client.post(f"{BASE}/import", json={"csv": (
            "question,answer,evidence,document,facets\n"
            "How often are uploads retried?,three times,retries failed uploads three times with exponential backoff,"
            "uploads.md,three times | exponential backoff\n")})
        assert imported.json()["added"] == 1 and await revision() == 3
        items = (await client.get(BASE)).json()["items"]
        assert [i["facets"] for i in items if i["question"] == "How often are uploads retried?"] == [
            ["three times", "exponential backoff"]]
        assert (await client.delete(f"{BASE}/items/{item['id']}")).status_code == 204 and await revision() == 4

        # a changed document -> the set says it was generated from different documents
        async with db.tx() as c:
            await c.execute("UPDATE documents SET content_sha='changed' WHERE id=?", (doc,))
        assert (await client.get(BASE)).json()["corpus_changed"] is True
        assert (await client.get("/api/projects/p/eval/sets")).json()[0]["corpus_changed"] is True


async def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE eval_items (id TEXT PRIMARY KEY, eval_set_id TEXT, ordinal INTEGER, question TEXT,"
                " gold_answer TEXT, evidence TEXT, document_id TEXT, gold_chunk_id TEXT, valid INTEGER,"
                " reject_reason TEXT, closed_book_answer TEXT)")
    old.execute("INSERT INTO eval_items (id) VALUES ('kept')")
    old.commit()
    old.close()
    await db.connect(path)
    try:
        await db.close()
        await db.connect(path)  # second start: nothing left to add, no error
        cols = {r["name"] for r in await db.fetch_all("PRAGMA table_info(eval_items)")}
        assert "facets" in cols and (await db.fetch_one("SELECT id, facets FROM eval_items")) == {"id": "kept", "facets": None}
        assert "revision" in {r["name"] for r in await db.fetch_all("PRAGMA table_info(eval_sets)")}
    finally:
        await db.close()
