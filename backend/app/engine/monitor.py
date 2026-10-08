"""Production query loop (FR-3.22): real questions keep feeding Corpus Health.

Every Playground/API answer records where its question came from (`runs.source`). A project can turn
on a monitor: once N new real questions have arrived since the last report, a new Corpus Health
report starts on its own — checked after each answer, so there is no scheduler to run. Each report
also compares itself with the previous one (`trend`): coverage up or down, gaps resolved, new gaps.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import db
from ..core import evalmetrics as M
from ..ingest import jobs


class MonitorSettings(BaseModel):
    enabled: bool = False
    every_n: int = Field(50, ge=5, le=10000)  # new real questions between automatic reports
    sources: Literal["all", "api"] = "all"  # "api": production traffic only, not Playground testing
    stale_days: int = Field(365, ge=1, le=3650)


async def settings(project_id: str) -> MonitorSettings:
    row = await db.fetch_one("SELECT settings FROM health_monitors WHERE project_id=?", (project_id,))
    return MonitorSettings.model_validate(db.loads(row["settings"], {})) if row else MonitorSettings()


async def save(project_id: str, s: MonitorSettings) -> None:
    async with db.tx() as c:
        await c.execute("INSERT INTO health_monitors (project_id, settings, updated_at) VALUES (?, ?, ?)"
                        " ON CONFLICT(project_id) DO UPDATE SET settings=excluded.settings, updated_at=excluded.updated_at",
                        (project_id, db.dumps(s.model_dump()), db.now_iso()))


async def since_last_report(project_id: str) -> dict[str, Any]:
    """New real questions (answered OK) since the latest report started, by source."""
    last = await db.fetch_one("SELECT created_at FROM corpus_reports WHERE project_id=? AND status != 'failed'"
                              " ORDER BY created_at DESC LIMIT 1", (project_id,))
    since = last["created_at"] if last else ""
    rows = await db.fetch_all("SELECT COALESCE(source, 'api') AS source, COUNT(*) AS n FROM runs WHERE project_id=?"
                              " AND kind='chat' AND status='ok' AND created_at > ? GROUP BY 1", (project_id, since))
    by = {r["source"]: r["n"] for r in rows}
    return {"last_report_at": since or None, "api": by.get("api", 0), "playground": by.get("playground", 0),
            "all": sum(by.values())}


async def maybe_trigger(project_id: str) -> str | None:
    """Start an automatic report if the monitor is on and enough new questions arrived. -> job id."""
    s = await settings(project_id)
    if not s.enabled:
        return None
    if any(j.kind == "health" for j in jobs.active_for(project_id)):
        return None
    if (await since_last_report(project_id))[s.sources] < s.every_n:
        return None
    from . import health, sync  # health imports chat; chat calls this

    v = await sync.active_version(project_id)
    if v is None:
        return None
    report_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO corpus_reports (id, project_id, version_id, questions, trigger, sources, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", (report_id, project_id, v["id"], "[]", "auto", s.sources, db.now_iso()))
    return jobs.start("health", project_id, lambda job: health.run_report(
        job, report_id, project_id, v, [], s.stale_days, sources=s.sources)).id


def outcomes(graded: list[dict[str, Any]], gaps: list[dict[str, Any]], misses: list[dict[str, Any]]) -> dict[str, str]:
    """Normalised question -> covered | gap | retrieval_miss (for the next report's trend)."""
    out = {M.normalize(q["question"]): "covered" for q in graded}
    out.update({M.normalize(q["question"]): "gap" for q in gaps})
    out.update({M.normalize(q["question"]): "retrieval_miss" for q in misses})
    return dict(list(out.items())[:2000])


def trend(prev: dict[str, Any] | None, cur_outcomes: dict[str, str], cur_rate: float) -> dict[str, Any] | None:
    """Against the previous ready report: coverage change and which questions moved."""
    if not prev:
        return None
    before = prev.get("coverage", {}).get("outcomes") or {}
    prev_rate = prev.get("coverage", {}).get("summary", {}).get("covered_rate")
    both = set(before) & set(cur_outcomes)
    return {
        "previous_covered_rate": prev_rate,
        "covered_rate_change": round(cur_rate - prev_rate, 4) if prev_rate is not None else None,
        "resolved": sum(before[q] != "covered" and cur_outcomes[q] == "covered" for q in both),
        "regressed": sum(before[q] == "covered" and cur_outcomes[q] != "covered" for q in both),
        "new_gaps": sum(v == "gap" and q not in before for q, v in cur_outcomes.items()),
        "new_questions": len(set(cur_outcomes) - set(before)),
    }
