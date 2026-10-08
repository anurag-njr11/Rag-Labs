"""Bring-your-own-RAG (PRD §8.7): an external HTTP system scored with the same metrics as a pipeline."""

import functools

import httpx
import pytest
from fastapi import FastAPI

from app import db
from app.core import evalmetrics as M
from app.engine import evaluate, external
from app.ingest.jobs import Job
from test_eval import project  # noqa: F401  (fixture)

EVIDENCE_1 = "retries failed uploads three times with exponential backoff"
EVIDENCE_2 = "capped at 250 megabytes and larger files are rejected"


def fake_rag(calls: list) -> FastAPI:
    """A RAG system elsewhere: answers the retries question with the right context at rank 2, the limits
    question with the right text but from the wrong file, and fails on anything else."""
    app = FastAPI()

    @app.post("/ask")
    async def ask(body: dict):
        calls.append(body["question"])
        q = body["question"]
        if "retried" in q:
            return {"answer": "Three times [1].", "contexts": [
                {"text": "Invoices are generated monthly.", "source": "docs/billing.md", "score": 0.9},
                {"text": f"The upload worker {EVIDENCE_1} before marking the file failed.",
                 "source": "docs/uploads.md", "score": 0.8}]}
        if "big" in q:
            return {"answer": "250 MB", "contexts": [
                {"text": f"Each upload is {EVIDENCE_2} with a clear error.", "source": "billing.md"}]}
        return {"nope": True}

    return app


@pytest.fixture
def remote(monkeypatch):
    calls: list = []
    asgi = httpx.ASGITransport(app=fake_rag(calls))
    monkeypatch.setattr(external.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=asgi))
    return calls


async def _eval_set(project):
    up = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_sets (id, project_id, size_requested, status, created_at)"
                        " VALUES ('s', 'p', 5, 'ready', ?)", (db.now_iso(),))
        await c.executemany(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id) VALUES (?, 's', ?, ?, ?, ?, ?, 'x')",
            [("i1", 0, "how many times are failed uploads retried", "three", EVIDENCE_1, up["id"]),
             ("i2", 1, "how big can an upload be", "250 MB", EVIDENCE_2, up["id"]),
             ("i3", 2, "what colour is the sky on mars", "butterscotch", "the martian sky is butterscotch", up["id"])])


def test_dig_and_mapping_paths():
    body = {"data": {"hits": [{"doc": {"body": "x"}}]}}
    assert external.dig(body, "data.hits.0.doc.body") == "x"
    assert external.dig(body, "data.hits.3") is None and external.dig(body, "data.nope.0") is None


def test_hit_matches_file_name_or_evidence_only():
    item = {"document_id": "d", "evidence": EVIDENCE_1, "filename": "uploads.md"}
    text = f"It {EVIDENCE_1}."
    assert M.is_hit({"text": text, "external_source": "docs/uploads.md?x=1"}, item)
    assert M.is_hit({"text": text, "external_source": ""}, item)  # no source given: evidence alone
    assert not M.is_hit({"text": text, "external_source": "billing.md"}, item)
    assert not M.is_hit({"text": "unrelated words", "external_source": "uploads.md"}, item)


def test_url_with_credentials_is_refused():
    with pytest.raises(ValueError):
        external.ExternalConfig(url="https://u:pw@host/ask")
    with pytest.raises(ValueError):
        external.ExternalConfig(url="ftp://host/ask")


async def test_external_run_scores_like_a_pipeline(project, remote):
    await _eval_set(project)
    system = await external.create("p", "My RAG", external.ExternalConfig(
        url="http://rag.test/ask", headers={"Authorization": "Bearer secret-token-123"}))
    raw = await db.fetch_one("SELECT config, headers FROM external_systems WHERE id=?", (system["id"],))
    assert "secret-token-123" not in raw["config"] + raw["headers"]  # encrypted at rest
    assert "secret-token-123" not in str(external.public(system))
    assert external.public(system)["config"]["header_names"] == ["Authorization"]

    version = {"id": system["id"], "config": db.dumps({"external": system["config"].model_dump()})}
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES ('r', 's', 'p', ?, ?)", (system["id"], db.now_iso()))
    await evaluate.run_eval(Job(id="j", kind="eval", project_id="p"), "r", "p", "s", version)

    run = await db.fetch_one("SELECT * FROM eval_runs WHERE id='r'")
    m, results = db.loads(run["metrics"]), db.loads(run["results"])
    assert run["status"] == "ready" and run["build_id"] is None
    # i1: evidence at rank 2; i2: right text but another file -> miss; i3: response has no contexts -> error
    assert [r["rank"] for r in results] == [2, None, None]
    assert results[1]["diagnosis"] == "not_retrieved" and results[2]["diagnosis"] is None and results[2]["error"]
    assert m["n"] == 3 and m["errors"] == 1 and m["hit_at_k"] == pytest.approx(1 / 3, abs=1e-3)
    assert m["mrr"] == pytest.approx(0.5 / 3, abs=1e-3) and m["cost_per_1k"] is None
    assert m["diagnoses"]["not_retrieved"] == 1 and m["config"]["external"] == "http://rag.test/ask"
    assert len(remote) == 3


async def test_every_question_failing_is_an_error(project, remote):
    await _eval_set(project)
    async with db.tx() as c:
        await c.execute("DELETE FROM eval_items WHERE id IN ('i1', 'i2')")
    cfg = {"external": external.ExternalConfig(url="http://rag.test/ask").model_dump()}
    with pytest.raises(evaluate.EvalError, match="No list of contexts"):
        await evaluate.score_config(Job(id="j", kind="eval", project_id="p"), "p", cfg,
                                    await evaluate.valid_items("s"))


async def test_answers_need_a_judge(project, remote):
    await _eval_set(project)
    cfg = {"external": external.ExternalConfig(url="http://rag.test/ask").model_dump()}
    with pytest.raises(evaluate.EvalError, match="judge"):
        await evaluate.score_config(Job(id="j", kind="eval", project_id="p"), "p", cfg,
                                    await evaluate.valid_items("s"), answers=True)


async def test_external_answers_are_graded(project, remote, monkeypatch):
    await _eval_set(project)
    async with db.tx() as c:
        await c.execute("DELETE FROM eval_items WHERE id != 'i1'")
    seen = {}

    async def fake_complete(provider, opts, system, user):
        seen["user"] = user
        return evaluate.json.dumps({"results": [{"id": 1, "correct": "yes", "grounded": "yes", "relevant": "yes",
                                                 "specificity": "right"}]})

    monkeypatch.setattr(evaluate, "complete", fake_complete)
    cfg = {"external": external.ExternalConfig(url="http://rag.test/ask").model_dump()}
    _, m, results = await evaluate.score_config(
        Job(id="j", kind="eval", project_id="p"), "p", cfg, await evaluate.valid_items("s"),
        answers=True, judge={"provider": "gemini", "model": "m"})
    assert "System answer: Three times [1]." in seen["user"] and "exponential backoff" in seen["user"]
    assert results[0]["correct"] == "yes" and m["answers"]["judge"] == "gemini/m"


async def test_api_register_test_and_list(project, remote):
    from app.main import app

    cfg = {"url": "http://rag.test/ask", "headers": {"X-Key": "s3cret-value"}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                 base_url="http://testserver") as c:
        r = await c.post("/api/projects/p/external/test", json={"config": cfg, "question": "how many are retried"})
        assert r.status_code == 200 and r.json()["contexts"][1]["external_source"] == "docs/uploads.md"
        bad = await c.post("/api/projects/p/external/test", json={"config": cfg, "question": "unknown thing"})
        assert bad.status_code == 502 and "No list of contexts" in bad.json()["detail"]
        made = await c.post("/api/projects/p/external", json={"name": "Mine", "config": cfg})
        assert made.status_code == 201 and "s3cret-value" not in made.text
        listed = (await c.get("/api/projects/p/external")).json()
        assert [x["name"] for x in listed] == ["Mine"]
        assert (await c.delete(f"/api/projects/p/external/{made.json()['id']}")).status_code == 204
        assert (await c.get("/api/projects/p/external")).json() == []


def test_cli_gate_exit_codes(remote, tmp_path, capsys):
    from app import cli

    csv_path = tmp_path / "eval.csv"
    rows = ["question,evidence,document",
            f"how many times are failed uploads retried,{EVIDENCE_1},uploads.md",
            f"how big can an upload be,{EVIDENCE_2},uploads.md"]
    csv_path.write_text(chr(10).join(rows), encoding="utf-8")
    argv = ["eval", "--endpoint", "http://rag.test/ask", "--set", str(csv_path)]
    # i1: evidence at rank 2 -> 1/2; i2: right text from the wrong file -> miss. MRR 0.25, Hit@8 0.5
    assert cli.main(argv + ["--min-mrr", "0.2", "--min-hit", "0.5"]) == 0
    assert "MRR 0.250" in capsys.readouterr().out
    assert cli.main(argv + ["--min-mrr", "0.5", "--json"]) == 1
    assert '"passed": false' in capsys.readouterr().out
    with pytest.raises(SystemExit) as bad:
        cli.main(["eval", "--endpoint", "ftp://x", "--set", str(csv_path)])
    assert bad.value.code == 2
