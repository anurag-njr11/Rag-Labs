"""Attested Computation (FR-3.21)."""

import json
import sqlite3

import httpx
import pytest

from app import db
from app.core.pipeline import validate_pipeline
from app.engine import chat
from app.engine import compute as C
from app.ingest import builder
from app.nodes import generate as G
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

SALES = ("﻿Region,Quarter,Revenue,Customers,Note\n"
         "EMEA,2026-Q1,\"1,250,000\",120,\n"
         "EMEA,2026-Q2,1310000.5,131,launch\n"
         "APAC,2026-Q1,980000,95,\n").encode()

REVENUE = {"name": "Quarterly revenue", "description": "Total revenue for a region in a quarter",
           "parameters": [{"name": "region", "type": "string", "options": ["EMEA", "APAC"]},
                          {"name": "quarter", "type": "string"}],
           "sql": "SELECT SUM(revenue) AS revenue FROM sales WHERE region = :region AND quarter = :quarter",
           "attester": {"min_rows": 1, "max_rows": 1, "columns": ["revenue"], "non_null": True,
                        "bounds": {"revenue": [0, 1e9]}},
           "unit": "USD"}


def test_csv_import_infers_types(project):  # noqa: F811
    out = C.import_csv("p", "Sales.csv", SALES)
    assert out["table"] == "sales" and out["rows"] == 3
    assert [(c["name"], c["type"]) for c in out["columns"]] == [
        ("region", "TEXT"), ("quarter", "TEXT"), ("revenue", "REAL"), ("customers", "INTEGER"), ("note", "TEXT")]
    con = sqlite3.connect(C.db_path("p"))
    assert con.execute("SELECT revenue, note FROM sales WHERE quarter='2026-Q1' AND region='EMEA'").fetchone() == (1250000.0, None)
    C.import_csv("p", "sales.csv", b"a\n1\n")  # same name replaces the table
    assert C.tables("p")[0]["rows"] == 1 and C.drop_table("p", "sales") and C.tables("p") == []
    with pytest.raises(C.ComputeError, match="header row"):
        C.import_csv("p", "x.csv", b"only,header\n")


def test_validation_rejects_unsafe_or_broken_sql(project):  # noqa: F811
    for bad, msg in [("DELETE FROM sales", "SELECT"), ("SELECT 1; DROP TABLE sales", "one statement"),
                     ("SELECT * FROM sales WHERE region = :nope", "undeclared")]:
        with pytest.raises(Exception, match=msg):
            C.Computation.model_validate({**REVENUE, "parameters": [], "sql": bad})
    C.import_csv("p", "sales.csv", SALES)
    with pytest.raises(C.ComputeError, match="SQL error"):
        C.check_sql("p", C.Computation.model_validate({**REVENUE, "sql": REVENUE["sql"].replace("revenue)", "revenu)")}))
    con = C._readonly(C.db_path("p"))
    with pytest.raises(sqlite3.Error):
        con.execute("CREATE TABLE evil (a)")  # read-only, whatever the SQL says


def test_coerce_execute_attest_render(project, monkeypatch):  # noqa: F811
    C.import_csv("p", "sales.csv", SALES)
    comp = C.Computation.model_validate(REVENUE)
    assert C.coerce(comp, {"region": "EMEA", "quarter": "2026-Q1"}) == {"region": "EMEA", "quarter": "2026-Q1"}
    for vals, msg in [({"region": "LATAM", "quarter": "x"}, "one of"), ({"region": "EMEA"}, "missing"),
                      ({"region": "EMEA", "quarter": "q", "sql": "x"}, "unknown")]:
        with pytest.raises(C.ComputeError, match=msg):
            C.coerce(comp, vals)
    num = C.Computation.model_validate({**REVENUE, "parameters": [{"name": "n", "type": "integer"},
                                                                  {"name": "d", "type": "date"}],
                                        "sql": "SELECT :n AS revenue, :d AS d"})
    assert C.coerce(num, {"n": "3", "d": "2026-01-31"}) == {"n": 3, "d": "2026-01-31"}
    with pytest.raises(C.ComputeError, match="integer"):
        C.coerce(num, {"n": 2.5, "d": "2026-01-31"})

    res = C.execute("p", comp, {"region": "EMEA", "quarter": "2026-Q2"})
    assert res["rows"] == [[1310000.5]] and all(c["ok"] for c in C.attest(comp.attester, res))
    assert C.render(comp, {"region": "EMEA", "quarter": "2026-Q2"}, res).endswith("**1,310,000.5 USD**")
    empty = C.execute("p", comp, {"region": "APAC", "quarter": "2026-Q2"})  # SUM over nothing = NULL
    failed = {c["check"] for c in C.attest(comp.attester, empty) if not c["ok"]}
    assert failed == {"non_null", "bounds:revenue"}

    monkeypatch.setattr(C, "TIMEOUT_S", 0.2)
    slow = C.Computation.model_validate({**REVENUE, "parameters": [], "sql":
                                         "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT max(n) FROM r"})
    with pytest.raises(C.ComputeError, match="too long"):
        C.execute("p", slow, {})


async def _setup(project, compute_cfg):
    C.import_csv("p", "sales.csv", SALES)
    async with db.tx() as c:
        await c.execute("INSERT INTO computations (id, project_id, spec, created_at, updated_at) VALUES ('rev', 'p', ?, ?, ?)",
                        (db.dumps(C.Computation.model_validate(REVENUE).model_dump(mode="json")), db.now_iso(), db.now_iso()))
    cfg = validate_pipeline({**_cfg("numpy"), "compute": compute_cfg, "cache": {"type": "semantic"}})
    await builder.sync_build(project, cfg)
    return await _version(cfg)


@pytest.fixture
def router(monkeypatch):
    state = {"route": None, "streams": 0}

    async def complete(self, prompt, max_tokens):
        assert "Quarterly revenue" in prompt and "you never write queries" in prompt.lower()
        return json.dumps(state["route"]), 30, 10

    async def stream(self, messages, usage):
        state["streams"] += 1
        yield "From the documents [1]."

    monkeypatch.setattr(G.ProviderGenerator, "complete", complete)
    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    return state


async def test_chat_answers_from_an_attested_computation(project, router):  # noqa: F811
    v = await _setup(project, {"type": "attested"})
    router["route"] = {"computation": "rev", "parameters": {"region": "EMEA", "quarter": "2026-Q2"}}
    done = [e async for e in chat.answer(project, v, "What was EMEA revenue in 2026-Q2?")][-1]
    assert router["streams"] == 0 and "**1,310,000.5 USD**" in done["answer"]
    comp = done["computation"]
    assert comp["attested"] and comp["sql"].startswith("SELECT") and comp["parameters"]["region"] == "EMEA"
    assert [s["step"] for s in done["trace"]] == ["cache_lookup", "compute_route", "compute"]
    run = await db.fetch_one("SELECT result FROM runs WHERE id=?", (done["run_id"],))
    assert db.loads(run["result"])["computation"]["attested"]
    assert (await db.fetch_one("SELECT COUNT(*) AS n FROM answer_cache"))["n"] == 0  # computed answers aren't cached


async def test_failed_attestation_falls_back_or_refuses(project, router):  # noqa: F811
    v = await _setup(project, {"type": "attested", "on_fail": "documents"})
    router["route"] = {"computation": "rev", "parameters": {"region": "APAC", "quarter": "2026-Q2"}}  # no rows
    done = [e async for e in chat.answer(project, v, "APAC revenue in 2026-Q2?")][-1]
    assert router["streams"] == 1 and done["answer"] == "From the documents [1]."
    assert done["computation"]["attested"] is False and any(not c["ok"] for c in done["computation"]["checks"])
    assert (await db.fetch_one("SELECT COUNT(*) AS n FROM answer_cache"))["n"] == 0  # routed: not cached either

    refuse = validate_pipeline({**db.loads(v["config"]), "compute": {"type": "attested", "on_fail": "refuse"}})
    v2 = await _version(refuse, "v2")
    router["route"] = {"computation": "rev", "parameters": {"region": "MARS", "quarter": "2026-Q2"}}  # bad value
    done = [e async for e in chat.answer(project, v2, "Mars revenue?")][-1]
    assert router["streams"] == 1 and "couldn't verify" in done["answer"] and "one of" in done["computation"]["error"]


async def test_unrelated_questions_go_to_the_documents(project, router):  # noqa: F811
    v = await _setup(project, {"type": "attested"})
    router["route"] = {"computation": None}
    done = [e async for e in chat.answer(project, v, "How are failed uploads retried?")][-1]
    assert router["streams"] == 1 and done["computation"] is None
    assert (await db.fetch_one("SELECT COUNT(*) AS n FROM answer_cache"))["n"] == 1  # an ordinary answer is cached


async def test_compute_api(project):  # noqa: F811
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await c.post("/api/projects/p/computations", json=REVENUE)).status_code == 422  # no data yet
        r = await c.post("/api/projects/p/data", files=[("files", ("sales.csv", SALES)), ("files", ("x.pdf", b"%PDF"))])
        assert r.status_code == 201 and r.json()["created"][0]["table"] == "sales" and r.json()["errors"]
        assert (await c.get("/api/projects/p/data")).json()[0]["rows"] == 3
        bad = await c.post("/api/projects/p/computations", json={**REVENUE, "sql": "UPDATE sales SET revenue = 0"})
        assert bad.status_code == 422 and "SELECT" in bad.json()["detail"]
        made = (await c.post("/api/projects/p/computations", json=REVENUE)).json()
        run = await c.post(f"/api/projects/p/computations/{made['id']}/run",
                           json={"parameters": {"region": "EMEA", "quarter": "2026-Q1"}})
        assert run.json()["attested"] and run.json()["result"]["rows"] == [[1250000.0]]
        assert (await c.post(f"/api/projects/p/computations/{made['id']}/run", json={"parameters": {}})).status_code == 422
        upd = await c.put(f"/api/projects/p/computations/{made['id']}", json={**REVENUE, "unit": "EUR"})
        assert upd.json()["unit"] == "EUR"
        assert (await c.delete(f"/api/projects/p/computations/{made['id']}")).status_code == 204
        assert (await c.delete("/api/projects/p/data/sales")).status_code == 204
        assert (await c.delete("/api/projects/p/data/sales")).status_code == 404
