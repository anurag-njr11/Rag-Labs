"""Grounding check (FR-3.5) and citation-support checking (FR-3.9)."""

import json

from app import db
from app.core.pipeline import index_config_hash, validate_pipeline, with_defaults
from app.core.node import RunContext
from app.engine import chat, evaluate, retrieval, sweep
from app.ingest import builder
from app.nodes import generate as G
from app.nodes import verify as V
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg


def _claims(*claims):
    return json.dumps({"claims": [{"claim": c, "cited": cited, "supported": s} for c, cited, s in claims]})


def test_parse_and_summarize():
    raw = "```json\n" + _claims(("A", {"1": "yes", "2": "no"}, "yes"), ("B", {"2": "partial", "9": "yes"}, "partial"),
                                ("C", {}, "maybe")) + "\n```"
    claims = V.parse_claims(raw, n_sources=2)
    assert [c["claim"] for c in claims] == ["A", "B"]  # unknown verdict dropped
    assert claims[1]["cited"] == {2: "partial"}  # source 9 doesn't exist
    s = V.summarize(claims)
    assert s["grounded"] is True and s["score"] == 0.75
    assert s["citations"] == {1: "yes", 2: "no"}  # worst verdict across the claims citing it

    assert V.summarize(V.parse_claims(_claims(("A", {}, "no")), 1))["grounded"] is False
    assert V.summarize([]) == {"status": "ok", "grounded": True, "score": 1.0, "claims": [], "citations": {}}
    assert V.summarize(V.parse_claims("not json", 1))["status"] == "error"


def test_more_context_doubles_within_limits():
    cfg = validate_pipeline({**_cfg("numpy"), "rerank": {"type": "cross_encoder", "top_n": 30}})
    new = V.more_context(cfg)
    assert new["retrieve"]["top_k"] == 2 * cfg["retrieve"]["top_k"]
    assert new["rerank"]["top_n"] == 50
    assert new["prompt"]["max_context_tokens"] == 2 * cfg["prompt"]["max_context_tokens"]
    validate_pipeline(new)


def test_configs_without_verify_slot_still_load():
    old = _cfg("numpy")
    old.pop("verify")
    assert validate_pipeline(old)["verify"] == {"type": "none", "validate_output": False}
    assert with_defaults(old)["verify"] == {"type": "none", "validate_output": False}
    assert index_config_hash(old) == index_config_hash(_cfg("numpy"))  # the slot never touches the index


async def test_chat_retries_with_more_context_until_grounded(project, monkeypatch):  # noqa: F811
    answers = iter(["Uploads retry five times [1].", "Failed uploads are retried three times [1]."])
    checks = iter([_claims(("five times", {"1": "no"}, "no")), _claims(("three times", {"1": "yes"}, "yes"))])

    async def stream(self, messages, usage):
        usage.update(tokens_in=100, tokens_out=10, finish_reason="stop")
        yield next(answers)

    async def complete(self, prompt, max_tokens):
        assert "Sources:\n[1]" in prompt
        return next(checks), 300, 40

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    monkeypatch.setattr(G.ProviderGenerator, "complete", complete)
    cfg = validate_pipeline({**_cfg("numpy"), "verify": {"type": "grounding_check"}})
    await builder.sync_build(project, cfg)
    events = [ev async for ev in chat.answer(project, await _version(cfg), "how many times are failed uploads retried")]

    types = [e["type"] for e in events]
    assert types.count("retry") == 1 and types.count("verify") == 2
    first, final = (e["verification"] for e in events if e["type"] == "verify")
    assert first["grounded"] is False and final["grounded"] is True and final["attempt"] == 1
    done = events[-1]
    assert done["answer"] == "Failed uploads are retried three times [1]."
    assert done["citations"][0]["support"] == "yes"
    steps = [s["step"] for s in done["trace"]]
    assert steps.count("generate") == 2 and steps.count("verify") == 2
    assert done["totals"]["tokens_in"] == 2 * (100 + 300)

    run = await db.fetch_one("SELECT result FROM runs WHERE version_id='v1'")
    assert db.loads(run["result"])["verification"]["grounded"] is True


async def test_flag_mode_and_failed_check_do_not_retry(project, monkeypatch):  # noqa: F811
    async def stream(self, messages, usage):
        yield "Uploads retry five times [1]."

    async def complete(self, prompt, max_tokens):
        return "sorry, no JSON here", 10, 5

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    monkeypatch.setattr(G.ProviderGenerator, "complete", complete)
    cfg = validate_pipeline({**_cfg("numpy"), "verify": {"type": "grounding_check", "on_fail": "flag"}})
    await builder.sync_build(project, cfg)
    events = [ev async for ev in chat.answer(project, await _version(cfg), "how many times are failed uploads retried")]
    assert "retry" not in [e["type"] for e in events]
    assert events[-1]["verification"]["status"] == "error" and events[-1]["verification"]["grounded"] is None


async def test_eval_answers_run_the_check_and_retry(project, monkeypatch):  # noqa: F811
    checks = iter([_claims(("five", {"1": "no"}, "no")), _claims(("three", {"1": "yes"}, "yes"))])

    async def stream(self, messages, usage):
        usage.update(tokens_in=10, tokens_out=5)
        yield "Three times [1]."

    async def complete(self, prompt, max_tokens):
        return next(checks), 20, 8

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    monkeypatch.setattr(G.ProviderGenerator, "complete", complete)
    cfg = validate_pipeline({**_cfg("numpy"), "verify": {"type": "grounding_check"}})
    build = await builder.sync_build(project, cfg)
    q = "how many times are failed uploads retried"
    final = await retrieval.retrieve(RunContext(), build=build, cfg=cfg, question=q)
    a = await evaluate.generate_answer(cfg, q, final, build)
    assert a["verification"] == {"status": "ok", "grounded": True, "score": 1.0, "attempt": 1, "claims": 1}
    assert a["ms"] >= 0 and a["answer"] == "Three times [1]."
    # without a build there's nothing to retrieve again: the failed check stands
    checks = iter([_claims(("five", {"1": "no"}, "no"))])
    assert (await evaluate.generate_answer(cfg, q, final))["verification"]["grounded"] is False


def test_verify_rollup_and_sweep_axis():
    from app.core import evalmetrics as M

    graded = [{"correct": "yes", "answer_ms": 100, "verification": {"status": "ok", "grounded": True, "score": 1.0, "attempt": 0}},
              {"correct": "no", "answer_ms": 300, "verification": {"status": "ok", "grounded": False, "score": 0.0, "attempt": 1}},
              {"correct": "yes", "answer_ms": 200, "verification": {"status": "error", "grounded": None, "score": None, "attempt": 0}}]
    s = M.answer_summary(graded)
    assert s["verify"] == {"checked": 2, "errors": 1, "pass_rate": 0.5, "retried": 1, "mean_score": 0.5}
    assert (s["answer_p50_ms"], s["answer_p95_ms"]) == (200, 300)
    assert "verify" not in M.answer_summary([{"correct": "yes"}])

    old = _cfg("numpy")
    old.pop("verify")
    cells = sweep.expand_grid(old, [{"path": "verify.type", "values": ["none", "grounding_check"]}])
    assert [c["config"]["verify"]["type"] for c in cells] == ["none", "grounding_check"]


async def test_output_validation_sends_one_checked_answer(project, monkeypatch):  # noqa: F811
    async def stream(self, messages, usage):
        for part in ["Retried three times [1]. ", "Details: https://evil.example/x", " or call +1 555 014 2234."]:
            yield part

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    cfg = validate_pipeline({**_cfg("numpy"), "verify": {"type": "none", "validate_output": True}})
    await builder.sync_build(project, cfg)
    events = [ev async for ev in chat.answer(project, await _version(cfg), "how many times are failed uploads retried")]
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert len(tokens) == 1 and "evil.example" not in tokens[0] and "014 2234" not in tokens[0]
    assert tokens[0].startswith("Retried three times [1].") and events[-1]["answer"] == tokens[0]
    (step,) = [s for s in events[-1]["trace"] if s["step"] == "output_validation"]
    assert step["payload"]["removed"] == 2
