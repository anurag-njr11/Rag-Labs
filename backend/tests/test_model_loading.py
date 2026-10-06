"""A first-use local model download that stalls must fail fast and clearly, not hang the caller."""

import threading
import time

import pytest

from app import db
from app.config import get_settings
from app.core.pipeline import validate_pipeline
from app.engine import chat, sweep, sync
from app.ingest import builder
from app.ingest.jobs import Job
from app.nodes import embed as E
from test_eval import _new_set, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

MSG = "Downloading {} timed out — check your connection and retry."


@pytest.fixture
def stalled(tmp_path, monkeypatch):
    """Tiny download timeout; fastembed's embedder and cross-encoder never finish loading."""
    release = threading.Event()

    class Stalled:
        def __init__(self, model_name, cache_dir):
            release.wait(30)
            raise RuntimeError("released")

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_DOWNLOAD_TIMEOUT_S", "0.3")
    get_settings.cache_clear()
    monkeypatch.setattr("fastembed.TextEmbedding", Stalled)
    monkeypatch.setattr("fastembed.rerank.cross_encoder.TextCrossEncoder", Stalled)
    yield
    release.set()  # let the abandoned loader threads finish
    get_settings.cache_clear()


def test_stalled_download_times_out_and_retry_starts_fresh(stalled):
    release, calls = threading.Event(), []

    def factory(model_name, cache_dir):
        calls.append(model_name)
        if len(calls) == 1:
            release.wait(30)  # the first attempt stalls
        return f"model:{model_name}"

    t0 = time.perf_counter()
    with pytest.raises(E.ModelLoadError, match="^" + MSG.format("org/m") + "$"):
        E.load_local_model(factory, "org/m")
    assert time.perf_counter() - t0 < 2
    # The stalled attempt was abandoned: the retry downloads afresh and is cached.
    assert E.load_local_model(factory, "org/m") == "model:org/m"
    assert E.load_local_model(factory, "org/m") == "model:org/m" and len(calls) == 2
    release.set()


async def test_build_job_fails_with_timeout_and_documents_stay_clean(project, stalled):  # noqa: F811
    cfg = _cfg("numpy")
    cfg["chunk"] = {"type": "semantic"}
    cfg = validate_pipeline(cfg)
    job = sync.start_sync(project, cfg)
    await job._task
    msg = MSG.format("BAAI/bge-small-en-v1.5")
    assert job.status == "failed" and job.error == msg
    b = await db.fetch_one("SELECT status, error FROM index_builds WHERE project_id='p'")
    assert (b["status"], b["error"]) == ("failed", msg)
    # A network stall isn't the document's fault: nothing is marked failed, so a retry re-indexes.
    assert await db.fetch_all("SELECT id FROM documents WHERE status='failed'") == []


async def test_chat_turn_reports_reranker_timeout(project, stalled):  # noqa: F811
    cfg = _cfg("numpy")
    cfg["rerank"] = {"type": "cross_encoder"}
    cfg = validate_pipeline(cfg)
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    with pytest.raises(chat.ChatError, match="^" + MSG.format("Xenova/ms-marco-MiniLM-L-6-v2") + "$"):
        async for _ in chat.answer(project, v, "how many times are failed uploads retried"):
            pass
    run = await db.fetch_one("SELECT status, error FROM runs WHERE version_id='v1'")
    assert run["status"] == "error" and "timed out" in run["error"]


async def test_sweep_cell_fails_with_timeout_and_sweep_continues(project, stalled):  # noqa: F811
    base = _cfg("numpy")
    v = await _version(base)
    await _new_set()
    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    async with db.tx() as c:
        await c.execute(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id) VALUES ('i1', 's', 0, 'how many times are failed uploads retried', 'three',"
            " 'retries failed uploads three times with exponential backoff', ?, 'x')", (doc["id"],))
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")
    cells = sweep.expand_grid(base, [{"path": "rerank.type", "values": ["none", "cross_encoder"]}])
    async with db.tx() as c:
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, created_at)"
                        " VALUES ('sw', 'p', 's', ?, '[]', ?, ?)", (v["id"], db.dumps(cells), db.now_iso()))

    await sweep.run_sweep(Job(id="j", kind="sweep", project_id="p"), "sw")
    row = await db.fetch_one("SELECT * FROM sweeps WHERE id='sw'")
    by_type = {c["overrides"]["rerank.type"]: c for c in db.loads(row["cells"])}
    assert row["status"] == "ready" and by_type["none"]["status"] == "ready"
    assert by_type["cross_encoder"]["status"] == "failed"
    assert by_type["cross_encoder"]["error"] == MSG.format("Xenova/ms-marco-MiniLM-L-6-v2")
