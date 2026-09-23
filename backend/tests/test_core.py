from app.core.cache import ArtifactCache, stable_hash
from app.core.node import RunContext
from app.core import runs


def test_stable_hash_ignores_key_order():
    assert stable_hash({"a": 1, "b": [1, 2]}) == stable_hash({"b": [1, 2], "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_artifact_cache_roundtrip(tmp_path):
    c = ArtifactCache(tmp_path)
    assert c.get("chunks", "abc123") is None
    c.put("chunks", "abc123", [{"text": "hi"}])
    assert c.get("chunks", "abc123") == [{"text": "hi"}]


def test_run_context_emit_and_totals():
    seen = []
    ctx = RunContext(listener=seen.append)
    ctx.emit("retrieve", ms=12.5, hits=3)
    with ctx.timed("generate") as t:
        t["tokens_in"] = 100
        t["tokens_out"] = 20
    assert [e.step for e in ctx.events] == ["retrieve", "generate"]
    assert [e.seq for e in ctx.events] == [0, 1]
    assert ctx.events[0].payload == {"hits": 3}
    assert ctx.totals["tokens_in"] == 100 and ctx.totals["tokens_out"] == 20
    assert len(seen) == 2


async def test_run_persists_events(database):
    async with database.tx() as c:
        await c.execute(
            "INSERT INTO projects (id, name, created_at) VALUES ('p1', 'P', ?)", (database.now_iso(),)
        )
    run_id = await runs.start_run(project_id="p1", version_id=None, build_id=None, question="q?")
    ctx = RunContext()
    ctx.emit("retrieve", ms=5, hits=2)
    ctx.emit("generate", ms=50, tokens_in=10, tokens_out=4, cost_usd=0.001)
    await runs.finish_run(run_id, ctx, status="ok", answer="a", result={"citations": []})
    run = await runs.get_run(run_id)
    assert run["status"] == "ok" and run["tokens_in"] == 10 and run["tokens_out"] == 4
    assert [e["step"] for e in run["events"]] == ["retrieve", "generate"]
    assert run["events"][0]["payload"] == {"hits": 2}
