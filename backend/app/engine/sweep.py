"""Config sweeps: score a grid of pipeline variants against one eval set.

A sweep varies a few fields of a base config (axes), scores every resulting
config with the same retrieval scoring as an eval run (LLM calls only for query
expansion cells and Auto-Optimize's answer grading), and marks
the Pareto set on quality (MRR) vs. cost (context tokens sent per query — what
the generator would bill). Both are deterministic, so a sweep re-run ranks the
same way. Cells are ordered by index hash so variants sharing an index are
scored back to back, and every build reuses the parse/chunk/vector caches.
"""

from __future__ import annotations

import itertools
import logging
import math
from typing import Any

from .. import db
from ..core import evalmetrics as M
from ..core.cache import stable_hash
from ..core.node import slot_types
from ..core.pipeline import PipelineError, default_for, index_config_hash, validate_pipeline
from ..ingest.document_analyzer import DocumentMetadata, aggregate_corpus_metadata
from ..ingest.jobs import Job
from ..nodes.embed import FASTEMBED_MODELS, mteb_label
from . import evaluate

log = logging.getLogger("raglabs.sweep")

MAX_CELLS = 48
GRADE_FRACTION = 0.25  # Auto-Optimize: answer-grade this share of cells, best by retrieval first
MAX_GRADED = 5

# Suggested axes for the UI. A sweep may vary any `slot.field` (or `slot.type`).
AXES: list[dict[str, Any]] = [
    {"path": "chunk.size", "label": "Chunk size", "effect": "rebuild", "values": [256, 512, 1000, 1500]},
    {"path": "chunk.type", "label": "Chunking strategy", "effect": "rebuild",
     "values": list(slot_types("chunk"))},
    # Best MTEB retrieval score first (FR-2.19); `seed` = the UI's "MTEB top 3" preset.
    {"path": "embed.model", "label": "Embedding model (local)", "effect": "rebuild",
     "values": sorted(FASTEMBED_MODELS, key=lambda m: -(FASTEMBED_MODELS[m]["mteb"] or 0)),
     "notes": {m: f"{mteb_label(m)} · {v['size']}" for m, v in FASTEMBED_MODELS.items()},
     "scores": {m: v["mteb"] for m, v in FASTEMBED_MODELS.items()},
     "seed": sorted(FASTEMBED_MODELS, key=lambda m: -(FASTEMBED_MODELS[m]["mteb"] or 0))[:3],
     "requires": {"embed.type": "fastembed"}},
    {"path": "retrieve.type", "label": "Retriever", "effect": "instant",
     "values": list(slot_types("retrieve"))},
    {"path": "retrieve.query_expansion", "label": "Query expansion", "effect": "instant",
     "values": ["none", "multi_query", "hyde"]},
    {"path": "retrieve.context_window", "label": "Context window", "effect": "instant", "values": [0, 1, 2]},
    {"path": "retrieve.top_k", "label": "Top k", "effect": "instant", "values": [3, 5, 8, 12]},
    {"path": "rerank.type", "label": "Reranker", "effect": "instant", "values": ["none", "cross_encoder"]},
]


class SweepError(ValueError):
    pass


def apply_override(cfg: dict[str, Any], path: str, value: Any) -> None:
    """Set `slot.field` in place. Changing `slot.type` resets the slot to that
    type's defaults, keeping any field the old and new types share."""
    slot, _, field = path.partition(".")
    if slot not in cfg or not field:
        raise SweepError(f"unknown axis {path!r}")
    if field == "type":
        try:
            fresh = default_for(slot, value)
        except KeyError as e:
            raise SweepError(f"unknown type {value!r} for {slot}") from e
        cfg[slot] = {k: cfg[slot].get(k, v) if k != "type" else v for k, v in fresh.items()}
    else:
        cfg[slot][field] = value


def expand_grid(base: dict[str, Any], axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cartesian product of the axes over `base`. Invalid combinations become
    'invalid' cells with the validation message; duplicates are dropped."""
    if not axes:
        raise SweepError("Pick at least one axis to vary.")
    paths = [a["path"] for a in axes]
    if len(set(paths)) != len(paths):
        raise SweepError("Each axis can appear only once.")
    if any(not a.get("values") for a in axes):
        raise SweepError("Every axis needs at least one value.")
    # Types first, so `chunk.type` × `chunk.size` sets the size on the new type.
    order = sorted(range(len(axes)), key=lambda i: not paths[i].endswith(".type"))
    cells, seen = [], set()
    for combo in itertools.product(*(a["values"] for a in axes)):
        overrides = dict(zip(paths, combo))
        cfg = {k: dict(v) for k, v in base.items()}
        try:
            for i in order:
                apply_override(cfg, paths[i], combo[i])
            if "chunk.size" in overrides and "chunk.overlap" not in overrides:
                # Keep the base overlap-to-size ratio, so a small size doesn't trip overlap >= size.
                ratio = base["chunk"].get("overlap", 0) / max(1, base["chunk"].get("size", 1))
                cfg["chunk"]["overlap"] = round(cfg["chunk"]["size"] * ratio)
            cfg = validate_pipeline(cfg)
        except (SweepError, PipelineError) as e:
            cells.append({"overrides": overrides, "config": None, "status": "invalid", "error": str(e)})
            continue
        key = stable_hash(cfg)
        if key in seen:
            continue
        seen.add(key)
        cells.append({"overrides": overrides, "config": cfg, "status": "pending", "error": None})
    runnable = sum(c["config"] is not None for c in cells)
    if runnable > MAX_CELLS:
        raise SweepError(f"That grid has {runnable} configurations; the limit is {MAX_CELLS}. Drop some values.")
    if runnable == 0:
        raise SweepError(cells[0]["error"] if cells else "No valid configurations in that grid.")
    return cells


def pareto(points: list[tuple[float, float]]) -> list[bool]:
    """For (quality, cost) points: True where no other point has quality >=
    and cost <= with at least one strictly better."""
    return [not any(q2 >= q and c2 <= c and (q2 > q or c2 < c) for q2, c2 in points) for q, c in points]


def mark_pareto(cells: list[dict[str, Any]]) -> None:
    done = [c for c in cells if c["status"] == "ready"]
    for c, on in zip(done, pareto([(c["metrics"]["mrr"], c["metrics"]["ctx_tokens"]) for c in done])):
        c["pareto"] = on


async def _save(sweep_id: str, cells: list[dict[str, Any]], status: str | None = None,
                error: str | None = None) -> None:
    async with db.tx() as c:
        await c.execute("UPDATE sweeps SET cells=? WHERE id=?", (db.dumps(cells), sweep_id))
        if status:  # never overwrite a cancel that landed mid-run
            await c.execute("UPDATE sweeps SET status=?, error=? WHERE id=? AND status='running'",
                            (status, error, sweep_id))


def to_grade(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Successive halving's second rung: the top quarter of finished cells by MRR
    (ties -> fewer context tokens), at least 1 and at most MAX_GRADED."""
    done = sorted((c for c in cells if c["status"] == "ready"),
                  key=lambda c: (-c["metrics"]["mrr"], c["metrics"]["ctx_tokens"]))
    return done[:min(MAX_GRADED, max(1, math.ceil(len(done) * GRADE_FRACTION)))] if done else []


def near_leader(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Graded cells too close to call (FR-2.8): the leader by correct rate plus every cell whose
    95% interval overlaps the leader's. Empty when the leader is clear (or nothing to compare)."""
    graded = [c for c in cells if (c.get("metrics") or {}).get("answers", {}).get("n")]
    if len(graded) < 2:
        return []
    lead = max(graded, key=lambda c: c["metrics"]["answers"]["correct_rate"])
    lo, hi = lead["metrics"]["answers"]["correct_ci"]
    close = [c for c in graded if c is not lead
             and c["metrics"]["answers"]["correct_ci"][1] >= lo and c["metrics"]["answers"]["correct_ci"][0] <= hi]
    return [lead, *close] if close else []


async def run_sweep(job: Job, sweep_id: str, auto_optimize: bool = False,
                    judge: dict[str, str] | None = None) -> dict[str, Any]:
    sweep = await db.fetch_one("SELECT * FROM sweeps WHERE id=?", (sweep_id,))
    assert sweep is not None
    cells = db.loads(sweep["cells"], [])
    try:
        items = await evaluate.valid_items(sweep["eval_set_id"])
        todo = sorted((c for c in cells if c["status"] == "pending"),
                      key=lambda c: index_config_hash(c["config"]))
        for n, cell in enumerate(todo, start=1):
            if not await _running(sweep_id):
                break  # cancelled (or deleted): finished cells stay valid
            job.progress("sweep", n - 1, len(todo), message=_label(cell))
            cell["status"] = "running"
            await _save(sweep_id, cells)
            try:
                build, metrics, _ = await evaluate.score_config(job, sweep["project_id"], cell["config"], items,
                                                                 stage=None)
                cell.update(status="ready", metrics=metrics, build_id=build["id"])
            except Exception as e:  # one bad cell (e.g. a model download failing) shouldn't sink the sweep
                cell.update(status="failed", error=str(e))
                job.log(f"{_label(cell)}: {e}", level="warning")
            mark_pareto(cells)
            await _save(sweep_id, cells)
        job.progress("sweep", len(todo), len(todo))
        if auto_optimize and await _running(sweep_id):
            await _grade_top(job, sweep, cells, items, judge)
        for c in cells:
            if c["status"] == "pending":
                c["status"] = "skipped"
        if not any(c["status"] == "ready" for c in cells) and any(c["status"] == "failed" for c in cells):
            raise evaluate.EvalError("No configuration finished. See the cell errors.")
        await _save(sweep_id, cells, status="ready")
        row = await db.fetch_one("SELECT status FROM sweeps WHERE id=?", (sweep_id,))
        if row is not None and row["status"] == "ready":  # a cancelled sweep's partial grid isn't a winner
            await record_fingerprint(sweep, cells, len(items))
    except Exception as e:
        await _save(sweep_id, cells, status="failed", error=str(e))
        raise
    return {"sweep_id": sweep_id, "ready": sum(c["status"] == "ready" for c in cells)}


async def _running(sweep_id: str) -> bool:
    row = await db.fetch_one("SELECT status FROM sweeps WHERE id=?", (sweep_id,))
    return row is not None and row["status"] == "running"


async def _grade_top(job: Job, sweep: dict[str, Any], cells: list[dict[str, Any]],
                     items: list[dict[str, Any]], judge: dict[str, str] | None = None) -> None:
    top = to_grade(cells)
    kept: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}  # id(cell) -> (judge inputs, results)
    for n, cell in enumerate(top, start=1):
        if not await _running(sweep["id"]):
            return  # Stop: no more LLM spend
        job.progress("grade_cells", n - 1, len(top), message=_label(cell))
        try:
            todo: list[dict[str, Any]] = []
            _, metrics, results = await evaluate.score_config(job, sweep["project_id"], cell["config"], items,
                                                              stage=None, answers=True, judge=judge, judged=todo)
            cell["metrics"]["answers"] = metrics["answers"]
            kept[id(cell)] = (todo, results)
        except Exception as e:  # keep the retrieval scores; just note why grading failed
            cell["grade_error"] = str(e)
            job.log(f"Grading {_label(cell)}: {e}", level="warning")
        await _save(sweep["id"], cells)
    job.progress("grade_cells", len(top), len(top))
    # Median-of-3 only where the call is close: cost stays bounded to the overlapping cells.
    close = [c for c in near_leader(top) if id(c) in kept]
    for cell in close:
        if not await _running(sweep["id"]):
            return
        job.log(f"Re-judging {_label(cell)} twice more: its answer score is within noise of the leader's")
        todo, results = kept[id(cell)]
        try:
            await evaluate.rejudge(job, cell["config"], judge, todo, results)
            cell["metrics"]["answers"] = {**M.answer_summary(results), "judge": cell["metrics"]["answers"]["judge"],
                                          "rejudged": True}
        except Exception as e:  # the single-judge verdicts stand
            job.log(f"Re-judging {_label(cell)}: {e}", level="warning")
        await _save(sweep["id"], cells)


async def corpus_fingerprint(project_id: str) -> dict[str, Any]:
    """Anonymised corpus profile: aggregate numbers and generic labels, never names or text."""
    rows = await db.fetch_all("SELECT metadata FROM document_metadata WHERE project_id=?", (project_id,))
    agg = aggregate_corpus_metadata([DocumentMetadata(**db.loads(r["metadata"], {})) for r in rows])
    return {"documents": len(rows), **{k: round(v, 4) if isinstance(v, float) else v for k, v in agg.items()}}


async def record_fingerprint(sweep: dict[str, Any], cells: list[dict[str, Any]], n_questions: int) -> None:
    """Log fingerprint -> winning settings -> score for a future config prior (FR-2.35).
    Best effort: instrumentation must never fail the sweep."""
    try:
        done = sorted((c for c in cells if c["status"] == "ready"),
                      key=lambda c: (-c["metrics"]["mrr"], c["metrics"]["ctx_tokens"]))
        if len(done) < 2:
            return  # nothing was compared
        pick = ("mrr", "hit_at_1", "hit_at_k", "ctx_tokens", "context_hit")

        def score(c: dict[str, Any]) -> dict[str, Any]:
            return {k: c["metrics"].get(k) for k in pick}

        async with db.tx() as c:
            await c.execute(
                "INSERT INTO sweep_fingerprints (id, sweep_id, fingerprint, axes, winner, score, n_cells, n_questions,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (db.new_id(), sweep["id"], db.dumps(await corpus_fingerprint(sweep["project_id"])),
                 db.dumps([a["path"] for a in db.loads(sweep["axes"], [])]),
                 db.dumps({"overrides": done[0]["overrides"], "config": done[0]["metrics"]["config"]}),
                 db.dumps({"winner": score(done[0]), "runner_up": score(done[1])}),
                 len(done), n_questions, db.now_iso()))
    except Exception:
        log.exception("could not record the sweep fingerprint for %s", sweep["id"])


def _label(cell: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in cell["overrides"].items())
