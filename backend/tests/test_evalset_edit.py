import httpx

from app import db
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
        assert csv_text.splitlines()[0] == "question,gold_answer,evidence,document,valid,reject_reason"
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
