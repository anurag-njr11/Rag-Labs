"""Background jobs with a progress bus.

Jobs run as asyncio tasks. Each keeps its recent events so a client that
connects late (or reconnects) still sees the history before live updates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from .. import db

log = logging.getLogger("raglabs.jobs")

MAX_EVENTS = 500


@dataclass
class Job:
    id: str
    kind: str
    project_id: str
    status: str = "running"  # running | done | failed
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    _subs: list[asyncio.Queue] = field(default_factory=list, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)

    def publish(self, event: dict[str, Any]) -> None:
        event = {"t": round(time.time() - self.created_at, 2), **event}
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        for q in list(self._subs):
            q.put_nowait(event)

    def progress(self, stage: str, done: int = 0, total: int = 0, message: str = "", **extra: Any) -> None:
        self.publish({"type": "progress", "stage": stage, "done": done, "total": total,
                      "message": message, **extra})

    def log(self, message: str, level: str = "info") -> None:
        self.publish({"type": "log", "level": level, "message": message})

    def summary(self) -> dict[str, Any]:
        last = next((e for e in reversed(self.events) if e["type"] == "progress"), None)
        return {"id": self.id, "kind": self.kind, "project_id": self.project_id, "status": self.status,
                "error": self.error, "result": self.result, "last": last}

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(self.events)
        self._subs.append(q)
        try:
            for e in backlog:
                yield e
            if self.status != "running":
                return
            while True:
                e = await q.get()
                yield e
                if e["type"] in ("done", "failed"):
                    return
        finally:
            self._subs.remove(q)


_jobs: dict[str, Job] = {}


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def active_for(project_id: str) -> list[Job]:
    return [j for j in _jobs.values() if j.project_id == project_id and j.status == "running"]


def start(kind: str, project_id: str, fn: Callable[[Job], Awaitable[dict[str, Any] | None]]) -> Job:
    job = Job(id=db.new_id(), kind=kind, project_id=project_id)
    _jobs[job.id] = job

    async def runner() -> None:
        try:
            result = await fn(job)
            job.result = result or {}
            job.status = "done"
            job.publish({"type": "done", "result": job.result})
        except Exception as e:  # surfaced to the UI, not swallowed
            log.exception("job %s (%s) failed", job.id, kind)
            job.status = "failed"
            job.error = str(e) or type(e).__name__
            job.publish({"type": "failed", "error": job.error})

    job._task = asyncio.create_task(runner())
    _prune()
    return job


def _prune(keep: int = 200) -> None:
    finished = sorted((j for j in _jobs.values() if j.status != "running"), key=lambda j: j.created_at)
    for j in finished[: max(0, len(finished) - keep)]:
        _jobs.pop(j.id, None)
