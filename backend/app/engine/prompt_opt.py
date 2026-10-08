"""Prompt optimisation (FR-3.11), DSPy-style, against the auto-generated eval set.

Prompt engineering by hand is tinkering; with a labelled set it becomes a search. This is the core of
DSPy's BootstrapFewShot + instruction proposal, implemented directly (no framework, PRD §2.3):

  1. Split the questions three ways, deterministically: train 40% · val 30% · test 30%.
  2. Bootstrap: answer the train questions with the current prompt; the best-scoring answers become
     few-shot examples (the model's own good answers, not hand-written ones).
  3. Propose: the Generate model reads the current system prompt and some scored train answers, and
     writes a few alternative instruction blocks.
  4. Select: every (instructions × with/without examples) candidate answers the val questions; the best
     mean score wins (ties → the shorter prompt).
  5. Report: the current prompt and the winner both answer the test questions — never used to choose —
     so the before/after isn't flattered by the search.

Score per answer (deterministic, cheap): token F1 against the gold answer, citation markers stripped,
halved when the answer breaks the citation contract. Retrieval runs once per question and is reused;
the Verify slot is left out here (its checks would multiply the cost, and it doesn't change the prompt).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from .. import db, vault
from ..core import evalmetrics as M
from ..core.node import RunContext, build_node
from ..core.pipeline import with_defaults
from ..ingest.jobs import Job
from ..llm import provider as llm
from . import chat, evaluate, retrieval

MIN_QUESTIONS = 9
N_CANDIDATES = 3
N_DEMOS = 2
DEMO_MIN_SCORE = 0.5

PROPOSE = """You improve the system prompt of a document question-answering assistant.

Its current system prompt:
---
{system}
---

Some questions it answered, with the reference answer and a score (token overlap with the reference, 0-1):
{examples}

Write {n} different blocks of additional instructions to append to the system prompt so that answers match
the references better — e.g. about length, directness, which details to include, wording. Each block at most
70 words. Keep the citation rules and never ask for information that isn't in the sources.
Reply with JSON only: {{"instructions": ["...", "..."]}}"""


def split(item_id: str) -> str:
    h = int(hashlib.sha256(item_id.encode()).hexdigest(), 16) % 100
    return "train" if h < 40 else "val" if h < 70 else "test"


def score(answer: str, gold: str, n_sources: int) -> float:
    f1 = M.token_f1(chat._CITE.sub(" ", answer), gold)
    return round(f1 * (0.5 if evaluate.format_problem(answer, n_sources) else 1.0), 4)


def patched(cfg: dict[str, Any], extra: str = "", examples: str = "") -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    out["prompt"] = {**out["prompt"], "extra_instructions": extra, "examples": examples}
    out["verify"] = {"type": "none", "validate_output": False}
    return out


def parse_instructions(text: str) -> list[str]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        got = json.loads(m.group(0) if m else text).get("instructions")
    except (ValueError, AttributeError):
        return []
    out = [" ".join(str(x).split()) for x in got or [] if isinstance(x, str) and str(x).strip()] if isinstance(got, list) else []
    return list(dict.fromkeys(out))


async def run(job: Job, run_id: str, project_id: str, version: dict[str, Any], set_id: str) -> dict[str, Any]:
    try:
        return await _run(job, run_id, project_id, version, set_id)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE prompt_runs SET status='failed', error=? WHERE id=?", (vault.redact(str(e)), run_id))
        raise


async def _run(job: Job, run_id: str, project_id: str, version: dict[str, Any], set_id: str) -> dict[str, Any]:
    cfg = with_defaults(db.loads(version["config"], {}))
    items = await evaluate.valid_items(set_id)
    if len(items) < MIN_QUESTIONS:
        raise evaluate.EvalError(f"Prompt optimisation needs at least {MIN_QUESTIONS} eval questions; this set has "
                                 f"{len(items)}. Generate a larger set.")
    parts: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    for it in items:
        parts[split(it["id"])].append(it)
    for name in ("val", "test"):  # a tiny set can leave a split empty: borrow from train
        if not parts[name] and len(parts["train"]) > 2:
            parts[name].append(parts["train"].pop())
    if not all(parts.values()):
        raise evaluate.EvalError("Couldn't split the eval set into train / val / test. Generate a larger set.")

    build = await evaluate.ready_build(project_id, cfg, job)
    finals: dict[str, list[dict[str, Any]]] = {}
    job.progress("retrieve", 0, len(items))
    for i, it in enumerate(items, start=1):
        ctx = RunContext()
        r = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=it["question"])
        finals[it["id"]] = await retrieval.rerank(ctx, cfg, it["question"], r)
        job.progress("retrieve", i, len(items))

    async def answer_all(c: dict[str, Any], its: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
        got, _ = await evaluate.gather_tolerant(
            [evaluate.generate_answer(c, it["question"], finals[it["id"]]) for it in its], job, stage)
        out = []
        for it, a in zip(its, got):
            if a:
                n = len(build_node("prompt", c["prompt"]).pack(finals[it["id"]])[0])
                out.append({"item_id": it["id"], "question": it["question"], "gold": it["gold_answer"],
                            "answer": a["answer"], "score": score(a["answer"], it["gold_answer"], n)})
        return out

    def mean(rows: list[dict[str, Any]]) -> float:
        return round(sum(r["score"] for r in rows) / len(rows), 4) if rows else 0.0

    base = patched(cfg, cfg["prompt"].get("extra_instructions", ""), cfg["prompt"].get("examples", ""))
    train = await answer_all(base, parts["train"], "bootstrap")
    good = sorted((r for r in train if r["score"] >= DEMO_MIN_SCORE), key=lambda r: -r["score"])[:N_DEMOS]
    demos = "\n\n".join(f"Q: {r['question']}\nA: {r['answer']}" for r in good)

    shown = "\n\n".join(f"Q: {r['question']}\nReference: {r['gold']}\nAnswer: {r['answer']}\nScore: {r['score']}"
                        for r in sorted(train, key=lambda r: r["score"])[:6])
    system = build_node("prompt", base["prompt"]).build("(question)", [])["messages"][0]["content"]
    provider, opts = evaluate.llm_settings(cfg)
    job.progress("propose", 0, 1)
    try:
        proposals = parse_instructions(await evaluate.complete(
            provider, {**opts, "temperature": 0.7}, "You write prompt instructions.",
            PROPOSE.format(system=system, examples=shown or "(none answered)", n=N_CANDIDATES)))[:N_CANDIDATES]
    except llm.ProviderError as e:
        job.log(f"Instruction proposals failed: {e}", level="warning")
        proposals = []
    job.progress("propose", 1, 1)

    current_extra = cfg["prompt"].get("extra_instructions", "")
    current = (current_extra, cfg["prompt"].get("examples", ""))
    pairs = dict.fromkeys([current, *((x, d) for x in [current_extra, *proposals] for d in ("", demos))])
    grid = [{"extra_instructions": x, "examples": d} for x, d in pairs]
    candidates = []
    for n, cand in enumerate(grid, start=1):
        job.progress("select", n - 1, len(grid))
        rows = await answer_all(patched(cfg, cand["extra_instructions"], cand["examples"]), parts["val"], "select")
        candidates.append({**cand, "val_score": mean(rows), "answered": len(rows),
                           "is_current": cand["extra_instructions"] == current_extra
                           and cand["examples"] == cfg["prompt"].get("examples", "")})
    job.progress("select", len(grid), len(grid))
    best = max(candidates, key=lambda c: (c["val_score"], -len(c["extra_instructions"]) - len(c["examples"])))

    before = await answer_all(base, parts["test"], "test")
    after = before if best["is_current"] else await answer_all(
        patched(cfg, best["extra_instructions"], best["examples"]), parts["test"], "test")
    by_id = {r["item_id"]: r for r in after}
    result = {
        "splits": {k: len(v) for k, v in parts.items()},
        "candidates": candidates,
        "best": {"extra_instructions": best["extra_instructions"], "examples": best["examples"],
                 "is_current": best["is_current"]},
        "test": {"before": mean(before), "after": mean(after), "n": len(before)},
        "improves": mean(after) > mean(before),
        "samples": [{"question": r["question"], "gold": r["gold"], "before": r["answer"], "before_score": r["score"],
                     "after": by_id[r["item_id"]]["answer"] if r["item_id"] in by_id else None,
                     "after_score": by_id[r["item_id"]]["score"] if r["item_id"] in by_id else None}
                    for r in before[:8]],
        "demos": len(good),
    }
    async with db.tx() as c:
        await c.execute("UPDATE prompt_runs SET status='ready', result=? WHERE id=?", (db.dumps(result), run_id))
    return {"prompt_run_id": run_id, "test_after": result["test"]["after"]}
