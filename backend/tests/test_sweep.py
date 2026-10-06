import pytest

from app import db
from app.engine import sweep
from app.ingest.jobs import Job
from test_eval import _new_set, _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def test_expand_grid_types_first_dedupe_and_invalid():
    base = _cfg("numpy")
    cells = sweep.expand_grid(base, [
        {"path": "chunk.size", "values": [300, 600]},
        {"path": "chunk.type", "values": ["fixed", "sentence"]},
    ])
    assert len(cells) == 4 and all(c["status"] == "pending" for c in cells)
    # the type change kept the size override instead of resetting it to the default
    assert {(c["config"]["chunk"]["type"], c["config"]["chunk"]["size"]) for c in cells} == {
        ("fixed", 300), ("fixed", 600), ("sentence", 300), ("sentence", 600)}
    # overlap follows the base overlap/size ratio rather than staying fixed
    ratio = base["chunk"]["overlap"] / base["chunk"]["size"]
    assert all(c["config"]["chunk"]["overlap"] == round(c["config"]["chunk"]["size"] * ratio) for c in cells)

    same = sweep.expand_grid(base, [{"path": "retrieve.top_k", "values": [base["retrieve"]["top_k"]] * 2}])
    assert len(same) == 1

    bad = sweep.expand_grid(base, [{"path": "retrieve.top_k", "values": [5, -1]}])
    assert [c["status"] for c in bad] == ["pending", "invalid"] and bad[1]["error"]

    with pytest.raises(sweep.SweepError):
        sweep.expand_grid(base, [{"path": "retrieve.top_k", "values": list(range(1, 50))}])
    with pytest.raises(sweep.SweepError):
        sweep.expand_grid(base, [{"path": "nope.x", "values": [1]}])


def test_pareto():
    # (quality, cost): b dominates d; a and c trade off; e ties a exactly (both kept)
    pts = [(0.8, 900), (0.6, 300), (0.9, 2000), (0.5, 400), (0.8, 900)]
    assert sweep.pareto(pts) == [True, True, True, False, True]


async def test_run_sweep_scores_every_cell(project):  # noqa: F811
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
    cells = sweep.expand_grid(base, [{"path": "chunk.size", "values": [120, 1000]},
                                     {"path": "retrieve.top_k", "values": [1, 5]}])
    async with db.tx() as c:
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, created_at)"
                        " VALUES ('sw', 'p', 's', ?, '[]', ?, ?)", (v["id"], db.dumps(cells), db.now_iso()))

    result = await sweep.run_sweep(Job(id="j", kind="sweep", project_id="p"), "sw")
    row = await db.fetch_one("SELECT * FROM sweeps WHERE id='sw'")
    cells = db.loads(row["cells"])
    assert row["status"] == "ready" and result["ready"] == 4
    assert all(c["status"] == "ready" and "ctx_tokens" in c["metrics"] for c in cells)
    assert any(c["pareto"] for c in cells)
    # two chunk sizes -> two builds, shared across the top_k variants
    assert len({c["build_id"] for c in cells}) == 2
    # config-prior instrumentation: one anonymised row, no file names
    fp = await db.fetch_one("SELECT * FROM sweep_fingerprints WHERE sweep_id='sw'")
    assert fp["n_cells"] == 4 and fp["n_questions"] == 1
    assert db.loads(fp["winner"])["overrides"] and "uploads.md" not in fp["fingerprint"] + fp["winner"]


async def test_cancelled_sweep_keeps_finished_cells(project):  # noqa: F811
    base = _cfg("numpy")
    v = await _version(base)
    await _new_set()
    doc = await db.fetch_one("SELECT id FROM documents LIMIT 1")
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence,"
                        " document_id, gold_chunk_id) VALUES ('i1', 's', 0, 'q', 'a', 'e', ?, 'x')", (doc["id"],))
        await c.execute("UPDATE eval_sets SET status='ready' WHERE id='s'")
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, status,"
                        " created_at) VALUES ('sw', 'p', 's', ?, '[]', ?, 'cancelled', ?)",
                        (v["id"], db.dumps(sweep.expand_grid(base, [{"path": "retrieve.top_k", "values": [1, 2]}])),
                         db.now_iso()))
    await sweep.run_sweep(Job(id="j", kind="sweep", project_id="p"), "sw")
    row = await db.fetch_one("SELECT * FROM sweeps WHERE id='sw'")
    assert row["status"] == "cancelled"
    assert {c["status"] for c in db.loads(row["cells"])} == {"skipped"}


def test_suggested_axes_cover_registered_types_and_expand():
    axes = {a["path"]: a for a in sweep.AXES}
    assert "semantic" in axes["chunk.type"]["values"] and "fused" in axes["retrieve.type"]["values"]
    base = _cfg("numpy")
    cells = sweep.expand_grid(base, [{"path": p, "values": axes[p]["values"]}
                                     for p in ("retrieve.query_expansion", "retrieve.context_window")])
    assert len(cells) == 9 and all(c["status"] == "pending" for c in cells)
