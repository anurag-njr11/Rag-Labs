import re

import pytest

import test_retrieval  # noqa: F401  (registers the deterministic test_hash embedder)
from app import db
from app.config import get_settings
from app.core import evalmetrics as M
from app.core.pipeline import validate_pipeline
from app.engine import evaluate, stores
from app.ingest import builder
from app.ingest.jobs import Job
from test_retrieval import _cfg

# --- pure metrics -------------------------------------------------------------


def test_summarize_and_mrr():
    m = M.summarize([1, 3, None, 2], k=5)
    assert m["n"] == 4 and m["hit_at_1"] == 0.25 and m["hit_at_3"] == 0.75 and m["hit_at_k"] == 0.75
    assert m["mrr"] == pytest.approx((1 + 1 / 3 + 1 / 2) / 4, abs=1e-4)
    assert M.summarize([], k=5)["hit_at_k"] == 0.0


def test_hit_is_chunking_independent():
    item = {"document_id": "d", "evidence": "Set **retries** to 5 to survive flaky networks."}
    big = {"document_id": "d", "text": "Intro.\n\nSet `retries` to 5 to survive flaky networks. More text."}
    other_doc = {**big, "document_id": "x"}
    split = {"document_id": "d", "text": "Set retries to 5 to survive flaky"}  # boundary cut, most tokens present
    unrelated = {"document_id": "d", "text": "Something else entirely about logging."}
    assert M.is_hit(big, item) and M.is_hit(split, item)
    assert not M.is_hit(other_doc, item) and not M.is_hit(unrelated, item)
    assert M.first_hit_rank([unrelated, other_doc, big], item) == 3


def test_token_f1():
    assert M.token_f1("Paris", "The capital is Paris") == pytest.approx(2 / 3)
    assert M.token_f1("unknown", "42 seconds") == 0.0


def test_sample_chunks_round_robin_and_deterministic():
    chunks = [{"id": f"{d}{i}", "document_id": d, "ordinal": i, "token_count": 50, "text": "x"}
              for d in "ab" for i in range(5)]
    chunks.append({"id": "tiny", "document_id": "a", "ordinal": 9, "token_count": 3, "text": "x"})
    s1 = M.sample_chunks(chunks, 4)
    assert s1 == M.sample_chunks(chunks, 4)
    assert sorted(c["document_id"] for c in s1) == ["a", "a", "b", "b"]
    assert all(c["id"] != "tiny" for c in M.sample_chunks(chunks, 100))


def test_parse_json_tolerates_fences():
    assert evaluate.parse_json('```json\n{"items": []}\n```') == {"items": []}
    assert evaluate.parse_json('Sure! {"a": 1} done') == {"a": 1}


def test_check_candidate_reasons():
    chunk = {"text": "The worker retries failed uploads three times before giving up."}
    good = {"chunk": chunk, "answer": "three times", "evidence": "retries failed uploads three times"}
    assert evaluate.check_candidate(good, "unknown") is None
    assert evaluate.check_candidate({**good, "evidence": "made up words not present"}, None).startswith("evidence")
    assert evaluate.check_candidate(good, "It retries three times").startswith("too generic")


# --- end to end on a real build -------------------------------------------------

LONG_DOCS = {
    "uploads.md": "# Uploads\n\n## Retries\n\n" + "The upload worker retries failed uploads three times with "
                  "exponential backoff before marking the file as failed. " * 3 +
                  "\n\n## Limits\n\n" + "Each upload is capped at 250 megabytes and larger files are rejected "
                  "with a clear error message shown to the user. " * 3,
    "billing.md": "# Billing\n\n## Invoices\n\n" + "Invoices are generated on the first business day of every "
                  "month and emailed to the billing contact on the account. " * 3,
}


@pytest.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_settings().ensure_dirs()
    await db.connect(get_settings().db_path)
    from app.ingest.documents import create_document

    async with db.tx() as c:
        await c.execute("INSERT INTO projects (id, name, created_at) VALUES ('p', 'P', ?)", (db.now_iso(),))
    for name, text in LONG_DOCS.items():
        await create_document("p", name, text.encode())
    yield "p"
    await stores.close_all()
    await db.close()
    get_settings.cache_clear()


async def _version(cfg, vid="v1"):
    async with db.tx() as c:
        await c.execute("INSERT INTO pipeline_versions (id, project_id, version, config, index_config_hash,"
                        " created_at) VALUES (?, 'p', ?, ?, '', ?)",
                        (vid, int(vid[1:]), db.dumps(cfg), db.now_iso()))
    return await db.fetch_one("SELECT * FROM pipeline_versions WHERE id=?", (vid,))


async def _new_set(set_id="s", size=30):
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_sets (id, project_id, size_requested, created_at) VALUES (?, 'p', ?, ?)",
                        (set_id, size, db.now_iso()))


async def test_generate_set_filters_generic_and_bad_evidence(project, monkeypatch):
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _new_set()

    async def fake_complete(provider, opts, system, user):
        if system == evaluate.GEN_SYSTEM:
            passages = re.split(r"### Passage \d+ \([^)]*\)\n", user)[1:]
            items = []
            for i, text in enumerate(passages, start=1):
                sentence = text.strip().split(". ")[0]
                if "Invoices" in text:
                    items.append({"passage": i, "question": "What is the capital of France?", "answer": "Paris",
                                  "evidence": sentence})
                elif "250 megabytes" in text:
                    items.append({"passage": i, "question": "How big can an upload be?", "answer": "250 MB",
                                  "evidence": "this sentence was never in the source text"})
                else:
                    items.append({"passage": i, "question": f"How often are failed uploads retried? ({i})",
                                  "answer": "three times with exponential backoff", "evidence": sentence})
            return '```json\n' + evaluate.json.dumps({"items": items}) + '\n```'
        qs = [ln.split(". ", 1)[1] for ln in user.splitlines()]
        return evaluate.json.dumps({"answers": [
            {"id": i, "answer": "Paris" if "France" in q else "unknown"} for i, q in enumerate(qs, start=1)]})

    monkeypatch.setattr(evaluate, "complete", fake_complete)
    job = Job(id="j", kind="evalset", project_id="p")
    result = await evaluate.generate_set(job, "s", "p", v, size=30)
    assert result["kept"] >= 1 and result["too_generic"] >= 1 and result["bad_evidence"] >= 1
    s = await db.fetch_one("SELECT * FROM eval_sets WHERE id='s'")
    assert s["status"] == "ready"
    rejected = await db.fetch_all("SELECT reject_reason FROM eval_items WHERE valid=0")
    assert {r["reject_reason"].split(":")[0] for r in rejected} >= {"too generic", "evidence not found in source"}


async def test_run_eval_scores_across_chunkings(project):
    cfg = _cfg("numpy")
    build = await builder.sync_build(project, cfg)
    await _new_set()
    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    chunk = await db.fetch_one("SELECT id FROM chunks WHERE build_id=? LIMIT 1", (build["id"],))
    async with db.tx() as c:
        await c.executemany(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id) VALUES (?, 's', ?, ?, ?, ?, ?, ?)",
            [("i1", 0, "how many times are failed uploads retried with backoff", "three",
              "retries failed uploads three times with exponential backoff", doc["id"], chunk["id"]),
             ("i2", 1, "what colour is the sky on mars", "butterscotch",
              "the martian sky is butterscotch coloured during the day", doc["id"], chunk["id"])])
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")

    for vid, chunk_cfg in (("v1", cfg), ("v2", None)):
        if chunk_cfg is None:
            chunk_cfg = dict(cfg)
            chunk_cfg["chunk"] = {**cfg["chunk"], "size": 120, "overlap": 0}
            chunk_cfg = validate_pipeline(chunk_cfg)
        v = await _version(chunk_cfg, vid)
        async with db.tx() as c:
            await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                            " VALUES (?, 's', 'p', ?, ?)", (f"r{vid}", vid, db.now_iso()))
        await evaluate.run_eval(Job(id="j", kind="eval", project_id="p"), f"r{vid}", "p", "s", v)
        run = await db.fetch_one("SELECT * FROM eval_runs WHERE id=?", (f"r{vid}",))
        assert run["status"] == "ready"
        metrics, results = db.loads(run["metrics"]), db.loads(run["results"])
        assert metrics["n"] == 2 and metrics["hit_at_k"] == 0.5
        by_item = {r["item_id"]: r for r in results}
        assert by_item["i1"]["hit"] and by_item["i1"]["rank"] >= 1
        assert by_item["i2"]["diagnosis"] == "not_retrieved"
