"""Config prior (FR-3.27)."""

import httpx

from app import db
from app.engine import prior
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

TECH = {"documents": 12, "total_char_count": 400000, "avg_structure_density": 0.2, "avg_code_density": 0.4,
        "total_table_count": 3, "ocr_needed": False}
LEGAL = {"documents": 3, "total_char_count": 2000000, "avg_structure_density": 0.01, "avg_code_density": 0.0,
         "total_table_count": 80, "ocr_needed": True}


def test_similarity_and_votes():
    assert prior.similarity(TECH, TECH) == 1.0 and prior.similarity(TECH, LEGAL) < prior.MIN_SIMILARITY
    rows = [{"fingerprint": TECH, "winner": {"overrides": {"rerank.type": "cross_encoder", "chunk.size": 512}}},
            {"fingerprint": {**TECH, "documents": 15}, "winner": {"overrides": {"rerank.type": "cross_encoder"}}},
            {"fingerprint": TECH, "winner": {"overrides": {"rerank.type": "none"}}},
            {"fingerprint": LEGAL, "winner": {"overrides": {"rerank.type": "none", "chunk.size": 1500}}}]
    s = {x["path"]: x for x in prior.predict(TECH, rows)}
    assert s["rerank.type"]["value"] == "cross_encoder" and s["rerank.type"]["sweeps"] == 3  # LEGAL too different
    assert 0 < s["chunk.size"]["confidence"] < s["rerank.type"]["confidence"] < 1  # 1 voter < 3 voters
    assert prior.predict(TECH, []) == []


async def test_endpoint_predicts_from_history_or_falls_back_to_rules(project, monkeypatch):  # noqa: F811
    from app.main import app
    from app.engine import sweep

    async def fp(project_id):
        return TECH

    monkeypatch.setattr(prior, "corpus_fingerprint", fp)
    monkeypatch.setattr(sweep, "corpus_fingerprint", fp)
    v = await _version(_cfg("numpy"))
    async with db.tx() as c:
        await c.execute("UPDATE projects SET active_version_id=? WHERE id='p'", (v["id"],))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        rules = (await c.get("/api/projects/p/config-prior")).json()
        assert rules["source"] == "rules" and rules["history"] == 0
        assert all(s["confidence"] is None for s in rules["suggestions"])
        async with db.tx() as tx:
            for i in range(3):
                await tx.execute("INSERT INTO sweep_fingerprints (id, sweep_id, fingerprint, axes, winner, score, n_cells,"
                                 " n_questions, created_at) VALUES (?, 's', ?, '[]', ?, '{}', 4, 20, ?)",
                                 (f"f{i}", db.dumps(TECH), db.dumps({"overrides": {"rerank.type": "cross_encoder"}}),
                                  db.now_iso()))
        got = (await c.get("/api/projects/p/config-prior")).json()
    assert got["source"] == "prior" and got["history"] == 3
    assert got["suggestions"][0]["path"] == "rerank.type" and got["suggestions"][0]["confidence"] > 0.5
    assert got["config"]["rerank"]["type"] == "cross_encoder"
    assert got["verify_axes"] == [{"path": "rerank.type", "values": ["none", "cross_encoder"]}]
