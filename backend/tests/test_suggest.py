from app import db
from app.engine import suggest
from app.ingest import builder
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def test_clean_heading():
    assert suggest.clean_heading("Guide > 2.3 Installation") == "Installation"
    assert suggest.clean_heading("IV. Retry policy") == "Retry policy"
    assert suggest.clean_heading("Chapter 3: `BaseModel` basics") == "BaseModel basics"
    assert suggest.clean_heading("Docs > Introduction") is None
    assert suggest.clean_heading("1.2") is None


async def _activate(cfg):
    v = await _version(cfg)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))


async def test_falls_back_from_nothing_to_headings_to_eval(project):  # noqa: F811
    assert await suggest.suggestions(project) == {"source": "none", "questions": []}

    cfg = _cfg("numpy")
    await _activate(cfg)
    await builder.sync_build(project, cfg)
    s = await suggest.suggestions(project)
    assert s["source"] == "headings" and len(s["questions"]) == 3
    # Nested sections, spread across both documents.
    assert sorted(s["questions"]) == sorted(f"Summarize the “{h}” section" for h in ("Retries", "Invoices", "Limits")), s

    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='billing.md'")
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_sets (id, project_id, status, size_requested, created_at)"
                        " VALUES ('s', 'p', 'ready', 1, ?)", (db.now_iso(),))
        await c.execute("INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence,"
                        " document_id, gold_chunk_id) VALUES ('i', 's', 0, 'When are invoices generated?',"
                        " 'first business day', 'x', ?, 'c')", (doc["id"],))
    assert await suggest.suggestions(project) == {"source": "eval", "questions": ["When are invoices generated?"]}


async def test_recent_questions_when_no_build(project):  # noqa: F811
    async with db.tx() as c:
        for i, q in enumerate(["How do retries work?", "How do retries work?", "What is the upload cap?"]):
            await c.execute("INSERT INTO runs (id, project_id, question, status, created_at) VALUES (?, 'p', ?, 'ok', ?)",
                            (f"r{i}", q, f"2026-01-0{i + 1}T00:00:00+00:00"))
    s = await suggest.suggestions(project)
    assert s == {"source": "recent", "questions": ["What is the upload cap?", "How do retries work?"]}
