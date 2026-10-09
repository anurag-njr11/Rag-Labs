"""FR-4.7: the Python SDK (score a RAG function in-process, or serve it) and OpenTelemetry trace ingestion."""

import functools

import httpx
import pytest
from fastapi import FastAPI
from test_eval import project  # noqa: F401  (fixture)
from test_external import EVIDENCE_1, EVIDENCE_2, _eval_set

import raglabs
from app import cli, db
from app.engine import evaluate, external, otel
from app.ingest.jobs import Job


def my_rag(question: str):
    """A RAG that's just a Python function: evidence at rank 2 for the retries question, plain strings."""
    if "retried" in question:
        return "Three times.", ["Invoices are generated monthly.", f"The upload worker {EVIDENCE_1}."]
    return [{"text": "Nothing relevant here.", "source": "billing.md"}]  # retrieval only


def _csv(tmp_path):
    p = tmp_path / "eval.csv"
    p.write_text("question,evidence\n"
                 f"how many times are failed uploads retried,{EVIDENCE_1}\n"
                 f"how big can an upload be,{EVIDENCE_2}\n", encoding="utf-8")
    return str(p)


def test_shape_accepts_dict_list_and_tuple():
    assert external.shape({"contexts": []}) == {"contexts": []}
    assert external.shape(["a"]) == {"contexts": ["a"]}
    assert external.shape(("ans", ["a"])) == {"answer": "ans", "contexts": ["a"]}
    with pytest.raises(external.ExternalError):
        external.shape("just a string")


async def test_call_runs_sync_and_async_functions():
    async def async_rag(q):
        return {"answer": " hi ", "contexts": [{"text": "t", "source": "a.md", "score": 0.5}]}

    got = await external.call(async_rag, "q")
    assert got["answer"] == "hi" and got["contexts"] == [{"text": "t", "external_source": "a.md", "score": 0.5}]
    assert (await external.call(my_rag, "retried?"))["contexts"][1]["text"].startswith("The upload worker")

    def broken(q):
        raise RuntimeError("index missing")

    with pytest.raises(external.ExternalError, match="RuntimeError: index missing"):
        await external.call(broken, "q")


def test_sdk_evaluate_scores_a_function(tmp_path):
    m = raglabs.evaluate(my_rag, _csv(tmp_path), min_mrr=0.2)
    # retries question: evidence at rank 2 -> 1/2; size question: not retrieved. MRR 0.25, Hit@8 0.5
    assert m["n"] == 2 and m["mrr"] == pytest.approx(0.25) and m["hit_at_k"] == 0.5 and m["passed"]
    assert not raglabs.evaluate(my_rag, _csv(tmp_path), min_hit=0.9)["passed"]


def test_cli_system_finds_the_decorated_function(tmp_path, capsys):
    mod = tmp_path / "their_rag.py"
    mod.write_text("import raglabs\n\n@raglabs.system\ndef ask(q):\n"
                   f"    return ['The upload worker {EVIDENCE_1}.']\n", encoding="utf-8")
    assert cli.main(["eval", "--system", str(mod), "--set", _csv(tmp_path), "--min-mrr", "0.5"]) == 0
    assert "MRR 0.500" in capsys.readouterr().out
    with pytest.raises(SystemExit) as both:
        cli.main(["eval", "--system", str(mod), "--endpoint", "http://x", "--set", _csv(tmp_path)])
    assert both.value.code == 2


async def test_serve_exposes_the_http_contract():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=raglabs.app_for(my_rag)),
                                 base_url="http://t") as c:
        body = (await c.post("/", json={"question": "how many times are failed uploads retried"})).json()
    assert body["answer"] == "Three times." and body["contexts"][1]["source"] is None
    # ... which the HTTP scorer reads back unchanged
    assert external.parse(body, external.ExternalConfig(url="http://x"))["contexts"][1]["text"].startswith("The")


def _otlp(trace_id: str, spans: list[tuple[str, str, str, int, int, dict]]) -> dict:
    def attr(k, v):
        return {"key": k, "value": {"intValue": str(v)} if isinstance(v, int) else {"stringValue": v}}

    return {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": trace_id, "spanId": sid, "parentSpanId": parent, "name": name,
         "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
         "attributes": [attr(k, v) for k, v in attrs.items()]}
        for sid, parent, name, start, end, attrs in spans]}]}]}


def test_otlp_protobuf_and_json_parse_the_same():
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.trace.v1.trace_pb2 import Span

    tid = "ab" * 16
    req = ExportTraceServiceRequest()
    span = req.resource_spans.add().scope_spans.add().spans.add()
    span.CopyFrom(Span(trace_id=bytes.fromhex(tid), span_id=bytes.fromhex("01" * 8), name="generate",
                       start_time_unix_nano=1_000_000, end_time_unix_nano=4_000_000))
    a = span.attributes.add()
    a.key, a.value.int_value = "gen_ai.usage.input_tokens", 120
    pb = otel.parse(req.SerializeToString(), "application/x-protobuf")
    js = otel.parse(db.dumps(_otlp(tid, [("01" * 8, "", "generate", 1_000_000, 4_000_000,
                                          {"gen_ai.usage.input_tokens": 120})])).encode(), "application/json")
    assert pb == js
    assert pb[0]["trace_id"] == tid and pb[0]["attrs"] == {"gen_ai.usage.input_tokens": 120}
    with pytest.raises(otel.OtelError):
        otel.parse(b"not protobuf \xff\xff", "application/x-protobuf")


@pytest.fixture
def traced(monkeypatch):
    """An external RAG that records the traceparent each request carries."""
    seen: list[str] = []
    app = FastAPI()

    @app.post("/ask")
    async def ask(body: dict, request: __import__("fastapi").Request):
        seen.append(request.headers.get("traceparent", ""))
        return {"answer": "Three times.", "contexts": [{"text": f"The upload worker {EVIDENCE_1}.", "source": "uploads.md"}]}

    monkeypatch.setattr(external.httpx, "AsyncClient",
                        functools.partial(httpx.AsyncClient, transport=httpx.ASGITransport(app=app)))
    return seen


async def test_exported_spans_show_up_on_the_eval_run(project, traced):  # noqa: F811
    await _eval_set(project)
    system = await external.create("p", "Traced RAG", external.ExternalConfig(url="http://rag.test/ask"))
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES ('r', 's', 'p', ?, ?)", (system["id"], db.now_iso()))
    version = {"id": system["id"], "config": db.dumps({"external": system["config"].model_dump()})}
    await evaluate.run_eval(Job(id="j", kind="eval", project_id="p"), "r", "p", "s", version)

    results = db.loads((await db.fetch_one("SELECT results FROM eval_runs WHERE id='r'"))["results"])
    tids = [r["trace_id"] for r in results]
    assert len(set(tids)) == 3 and [t.split("-")[1] for t in traced] == tids  # one fresh trace per question

    # The system's exporter sends spans for the first question only (the others never export).
    ms, t = 1_000_000, 1_760_000_000 * 10**9  # unix-epoch nanoseconds, like a real exporter
    export = _otlp(tids[0], [
        ("a" * 16, "f" * 16, "POST /ask", t, t + 900 * ms, {}),  # parent = the span we sent in traceparent
        ("b" * 16, "a" * 16, "retrieve", t + 10 * ms, t + 110 * ms, {}),
        ("c" * 16, "a" * 16, "generate", t + 120 * ms, t + 880 * ms,
         {"gen_ai.request.model": "gemini-3.5-flash", "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 50}),
    ])
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.post("/api/otel/v1/traces", json=export)
        assert r.status_code == 200 and r.json() == {}
        assert (await c.post("/api/otel/v1/traces", content=b"{", headers={"content-type": "application/json"})
                ).status_code == 400
        run = (await c.get("/api/projects/p/eval/runs/r")).json()

    steps = run["results"][0]["steps"]
    assert [s["step"] for s in steps] == ["POST /ask", "retrieve", "generate"]
    gen = steps[2]
    assert gen["ms"] == 760 and gen["start_ms"] == 120 and gen["tokens_in"] == 1000 and gen["tokens_out"] == 50
    assert gen["payload"]["model"] == "gemini-3.5-flash" and gen["payload"]["priced"] and gen["cost_usd"] > 0
    assert run["results"][1]["steps"] == []
    assert run["trace_summary"] == [  # root span left out: where the time goes inside the system
        {"step": "retrieve", "n": 1, "start_ms": 10, "p50_ms": 100, "p95_ms": 100, "tokens_in": 0, "tokens_out": 0},
        {"step": "generate", "n": 1, "start_ms": 120, "p50_ms": 760, "p95_ms": 760, "tokens_in": 1000, "tokens_out": 50}]


async def test_a_chat_key_may_export_traces_but_nothing_else(database):
    from app import access
    from app.main import app

    async with db.tx() as c:
        await c.execute("INSERT INTO projects (id, name, created_at) VALUES ('p', 'P', ?)", (db.now_iso(),))
    key = await access.create_key("exporter", "chat", "p")
    remote = httpx.ASGITransport(app=app, client=("203.0.113.5", 1))
    async with httpx.AsyncClient(transport=remote, base_url="http://testserver",
                                 headers={"Authorization": f"Bearer {key['key']}"}) as c:
        assert (await c.post("/api/otel/v1/traces", json={"resourceSpans": []})).status_code == 200
        assert (await c.get("/api/projects")).status_code == 403


def test_sdk_works_in_a_project_with_its_own_app_package(tmp_path):
    """Lots of projects have an `app` package; it sits first on sys.path and must not shadow the SDK's backend."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("USER_APP = True\n", encoding="utf-8")
    (tmp_path / "run.py").write_text(
        "import app, raglabs\nassert app.USER_APP\n"
        f"print(raglabs.evaluate(lambda q: ['The upload worker {EVIDENCE_1}.'], {_csv(tmp_path)!r})['mrr'])\n",
        encoding="utf-8")
    backend = str(Path(__file__).resolve().parent.parent)
    out = subprocess.run([sys.executable, "run.py"], cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False,
                         env={**os.environ, "PYTHONPATH": backend})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0.5"


def test_junk_token_attributes_count_as_zero():
    row = {"trace_id": "ab" * 16, "span_id": "01" * 8, "parent_id": "", "name": "generate", "start_ns": 1, "end_ns": 2,
           "attrs": db.dumps({"gen_ai.usage.input_tokens": "lots", "gen_ai.usage.output_tokens": -5})}
    step = otel.to_steps([row])[0]
    assert step["tokens_in"] == 0 and step["tokens_out"] == 0
