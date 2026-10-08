"""Domain embedding adapter (FR-3.10, 3.12)."""

import importlib.util
import io
import zipfile

import numpy as np
import pytest

from app import db
from app.core.node import RunContext, build_node
from app.core.pipeline import validate_pipeline
from app.engine import adapter as A
from app.engine import retrieval
from app.ingest import builder
from app.ingest.jobs import Job
from test_eval import _new_set, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def _synthetic(seed: int, n: int, m: int = 60, d: int = 16):
    """One fixed corpus; queries (drawn with `seed`) are a fixed rotation, plus noise, of their positive
    chunk: plain cosine ranks them badly, a linear query map can undo the rotation."""
    c = np.random.default_rng(7).normal(size=(m, d)).astype(np.float32)
    rng = np.random.default_rng(seed)
    rot, _ = np.linalg.qr(np.random.default_rng(99).normal(size=(d, d)))
    pos = [[int(i)] for i in rng.integers(0, m, size=n)]
    q = np.stack([rot @ c[p[0]] + 0.1 * rng.normal(size=d) for p in pos]).astype(np.float32)
    return q, c, pos


def test_fit_learns_a_transform_that_generalises():
    q, c, pos = _synthetic(1, 200)
    w = A.fit(q, c, pos, steps=400, lr=5e-3, lam=0.0)
    hq, _, hpos = _synthetic(2, 50)  # unseen queries, same corpus and rotation
    before, after = A.rank_metrics(hq, c, hpos), A.rank_metrics(hq, c, hpos, w)
    assert before["mrr"] < 0.5 and after["mrr"] > 0.9 and after["recall_at_k"] > before["recall_at_k"]


def test_identity_regularisation_and_apply():
    q, c, pos = _synthetic(3, 20)
    w = A.fit(q, c, pos, steps=50, lam=1e6)  # an overwhelming pull to the identity
    assert np.allclose(w, np.eye(q.shape[1]), atol=1e-3)
    v = np.array([3.0, 4.0], np.float32)
    out = A.apply(np.array([[0, 1], [1, 0]], np.float32), v)
    assert np.allclose(out, [4, 3]) and np.isclose(np.linalg.norm(out), 5)


def test_holdout_split_is_deterministic():
    ids = [f"item{i}" for i in range(400)]
    s = A.split(ids)
    assert s == A.split(ids) and 0.18 < sum(s) / len(s) < 0.32


async def _items(project, n=6):
    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    await _new_set()
    qs = ["how many times are failed uploads retried", "what happens when an upload keeps failing",
          "retry policy for uploads", "is a failed upload retried", "upload size cap", "largest file I can upload"]
    ev = ["retries failed uploads three times"] * 4 + ["Each upload is capped at 250 megabytes"] * 2
    async with db.tx() as c:
        await c.executemany("INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence,"
                            " document_id, gold_chunk_id) VALUES (?, 's', ?, ?, 'x', ?, ?, 'x')",
                            [(f"i{i}", i, q, e, doc["id"]) for i, (q, e) in enumerate(zip(qs[:n], ev[:n]))])
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")


async def test_train_apply_and_skip(project, monkeypatch):  # noqa: F811
    monkeypatch.setattr(A, "MIN_QUESTIONS", 4)
    monkeypatch.setattr(A, "STEPS", 30)
    cfg = _cfg("numpy")
    build = await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _items(project)
    async with db.tx() as c:
        await c.execute("INSERT INTO adapters (id, project_id, version_id, eval_set_id, created_at)"
                        " VALUES ('ad', 'p', 'v1', 's', ?)", (db.now_iso(),))
    await A.train(Job(id="j", kind="adapter", project_id="p"), "ad", "p", v, "s")
    row = await db.fetch_one("SELECT * FROM adapters WHERE id='ad'")
    m = db.loads(row["metrics"])
    assert row["status"] == "ready" and m["questions"] == 6 and m["holdout"]["before"]["n"] >= 1
    assert A.adapter_path("p", "ad").exists() and row["embed_key"] == build_node("embed", cfg["embed"]).embed_key()

    acfg = validate_pipeline({**cfg, "retrieve": {**cfg["retrieve"], "adapter": "ad"}})
    ctx = RunContext()
    await retrieval.retrieve(ctx, build=build, cfg=acfg, question="upload retries")
    (emb,) = [e for e in ctx.events if e.step == "embed_query"]
    assert emb.payload["adapter"] == "ad"

    async with db.tx() as c:  # trained for another embedder → skipped, and the trace says why
        await c.execute("UPDATE adapters SET embed_key='other' WHERE id='ad'")
    ctx = RunContext()
    await retrieval.retrieve(ctx, build=build, cfg=acfg, question="upload retries")
    (emb,) = [e for e in ctx.events if e.step == "embed_query"]
    assert emb.payload["adapter"].startswith("skipped")


async def test_too_few_questions_fails_clearly(project):  # noqa: F811
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    v = await _version(cfg)
    await _items(project, n=3)
    async with db.tx() as c:
        await c.execute("INSERT INTO adapters (id, project_id, created_at) VALUES ('ad', 'p', ?)", (db.now_iso(),))
    with pytest.raises(Exception, match="at least 8"):
        await A.train(Job(id="j", kind="adapter", project_id="p"), "ad", "p", v, "s")
    assert (await db.fetch_one("SELECT status FROM adapters WHERE id='ad'"))["status"] == "failed"


async def test_export_ships_the_adapter_and_ranks_like_live(project, tmp_path, monkeypatch):  # noqa: F811
    from app.api.projects import export_version
    from test_export import _hash_query

    cfg = _cfg("numpy")
    build = await builder.sync_build(project, cfg)
    key = build_node("embed", cfg["embed"]).embed_key()
    d = int(build["dim"])
    w = (np.eye(d) + 0.3 * np.random.default_rng(0).normal(size=(d, d))).astype(np.float32)
    A.adapter_path("p", "ad").parent.mkdir(parents=True, exist_ok=True)
    np.save(A.adapter_path("p", "ad"), w)
    async with db.tx() as c:
        await c.execute("INSERT INTO adapters (id, project_id, status, embed_key, created_at)"
                        " VALUES ('ad', 'p', 'ready', ?, ?)", (key, db.now_iso()))
    acfg = validate_pipeline({**cfg, "retrieve": {**cfg["retrieve"], "adapter": "ad", "type": "dense"}})
    v = await _version(acfg)
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id='v1' WHERE id='p'")
    zf = zipfile.ZipFile(io.BytesIO((await export_version("p", "v1")).body))
    assert "data/adapter.npy" in zf.namelist() and "adapter.npy" in zf.read("README.md").decode()
    out = tmp_path / "export"
    zf.extractall(out)
    spec = importlib.util.spec_from_file_location("rag_adapter_test", out / "rag.py")
    rag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rag)
    monkeypatch.setattr(rag, "_embed_query", lambda t, as_passage=False: _hash_query(t))
    q = "how many times are failed uploads retried"
    live = await retrieval.retrieve(RunContext(), build=build, cfg=acfg, question=q)
    exported = rag.retrieve(q)
    assert [r["id"] for r in exported] == [r["id"] for r in live]
    plain = await retrieval.retrieve(RunContext(), build=build, cfg=validate_pipeline(
        {**acfg, "retrieve": {**acfg["retrieve"], "adapter": ""}}), question=q)
    assert [r["score"] for r in plain] != [r["score"] for r in live]  # the adapter did change the scores
    assert v["id"] == "v1"


def test_cross_validation_picks_identity_when_nothing_generalises():
    rng = np.random.default_rng(100)
    c = rng.normal(size=(40, 8)).astype(np.float32)
    q = rng.normal(size=(18, 8)).astype(np.float32)  # queries unrelated to their "positives": pure noise
    pos = [[int(i)] for i in rng.integers(0, 40, size=18)]
    lam, cv, passed = A.choose_lambda(q, c, pos, steps=60)
    assert lam == A.LAMBDAS[-1] and "identity" in cv and not passed

    q2, c2, pos2 = _synthetic(1, 60)  # a real, learnable transform: a small λ should win
    lam2, cv2, passed2 = A.choose_lambda(q2, c2, pos2, steps=200)
    assert passed2 and lam2 < A.LAMBDAS[-1] and cv2[str(lam2)] > cv2["identity"]
