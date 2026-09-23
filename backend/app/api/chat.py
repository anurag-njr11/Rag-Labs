from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import db
from ..core import runs
from ..engine import chat as chat_engine
from ..engine import sync

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    version_id: str | None = None
    stream: bool = True


async def _version_for(project_id: str, version_id: str | None) -> dict[str, Any]:
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")
    if version_id:
        v = await db.fetch_one("SELECT * FROM pipeline_versions WHERE id=? AND project_id=?",
                               (version_id, project_id))
    else:
        v = await sync.active_version(project_id)
    if v is None:
        raise HTTPException(404, "version not found")
    return v


@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatIn):
    version = await _version_for(project_id, body.version_id)

    if body.stream:
        async def gen():
            try:
                async for ev in chat_engine.answer(project_id, version, body.question):
                    yield {"event": ev["type"], "data": json.dumps(ev, default=str)}
            except chat_engine.ChatError as e:
                yield {"event": "error", "data": json.dumps({"type": "error", "code": e.code, "message": str(e)})}

        return EventSourceResponse(gen())

    final: dict[str, Any] | None = None
    try:
        async for ev in chat_engine.answer(project_id, version, body.question):
            if ev["type"] == "done":
                final = ev
    except chat_engine.ChatError as e:
        raise HTTPException(409 if e.code in ("no_documents", "build_failed") else 502,
                            {"code": e.code, "message": str(e)}) from e
    assert final is not None
    return {
        "answer": final["answer"],
        "citations": final["citations"],
        "sources": [{k: r[k] for k in ("rank", "document", "page_start", "page_end", "heading_path",
                                        "found_by", "scores", "cited", "text")} for r in final["retrieved"]],
        "run_id": final["run_id"],
        "totals": final["totals"],
    }


@router.get("/projects/{project_id}/runs")
async def list_runs(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return await runs.list_runs(project_id, min(limit, 200))


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    r = await runs.get_run(run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r
