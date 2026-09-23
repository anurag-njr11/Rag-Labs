"""Run records and their trace events: the per-step cost/latency ledger.

Every chat turn writes one run plus all the events its nodes emitted, so
metrics, trace views and cost reporting are queries, not new instrumentation.
"""

from __future__ import annotations

from typing import Any

from .. import db
from .node import RunContext


async def start_run(
    *, project_id: str, version_id: str | None, build_id: str | None,
    question: str, kind: str = "chat",
) -> str:
    run_id = db.new_id()
    async with db.tx() as c:
        await c.execute(
            "INSERT INTO runs (id, project_id, version_id, build_id, kind, question, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, project_id, version_id, build_id, kind, question, db.now_iso()),
        )
    return run_id


async def finish_run(
    run_id: str, ctx: RunContext, *, status: str, answer: str = "",
    error: str | None = None, result: dict[str, Any] | None = None,
    latency_ms: float | None = None,
) -> None:
    totals = ctx.totals
    async with db.tx() as c:
        await c.executemany(
            "INSERT INTO trace_events (run_id, seq, step, ms, tokens_in, tokens_out, cost_usd, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, e.seq, e.step, e.ms, e.tokens_in, e.tokens_out, e.cost_usd, db.dumps(e.payload))
                for e in ctx.events
            ],
        )
        await c.execute(
            "UPDATE runs SET status=?, answer=?, error=?, result=?, latency_ms=?,"
            " tokens_in=?, tokens_out=?, cost_usd=? WHERE id=?",
            (
                status, answer, error, db.dumps(result or {}),
                latency_ms if latency_ms is not None else totals["ms"],
                totals["tokens_in"], totals["tokens_out"], totals["cost_usd"], run_id,
            ),
        )


def _run_row(row: dict[str, Any]) -> dict[str, Any]:
    row["result"] = db.loads(row.get("result"), {})
    return row


async def get_run(run_id: str) -> dict[str, Any] | None:
    row = await db.fetch_one("SELECT * FROM runs WHERE id=?", (run_id,))
    if row is None:
        return None
    events = await db.fetch_all(
        "SELECT seq, step, ms, tokens_in, tokens_out, cost_usd, payload"
        " FROM trace_events WHERE run_id=? ORDER BY seq",
        (run_id,),
    )
    for e in events:
        e["payload"] = db.loads(e["payload"], {})
    out = _run_row(row)
    out["events"] = events
    return out


async def list_runs(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT id, version_id, question, status, latency_ms, tokens_in, tokens_out,"
        " cost_usd, created_at FROM runs WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    )
    return rows
