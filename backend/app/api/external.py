"""Bring-your-own-RAG systems (PRD §8.7): register an HTTP endpoint, test it, score it from the Evaluate tab."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .. import db
from ..engine import external

router = APIRouter(prefix="/api/projects/{project_id}/external", tags=["external"])

SAMPLE_QUESTION = "What is this documentation about?"


class SystemIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    config: external.ExternalConfig


class TestIn(BaseModel):
    config: external.ExternalConfig
    question: str | None = Field(None, min_length=3, max_length=1000)


async def _project(project_id: str) -> None:
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")


@router.get("")
async def list_systems(project_id: str) -> list[dict[str, Any]]:
    await _project(project_id)
    rows = await db.fetch_all("SELECT id FROM external_systems WHERE project_id=? ORDER BY created_at", (project_id,))
    return [external.public(await external.get(project_id, r["id"])) for r in rows]  # type: ignore[arg-type]


@router.post("", status_code=201)
async def create_system(project_id: str, body: SystemIn) -> dict[str, Any]:
    await _project(project_id)
    return external.public(await external.create(project_id, body.name.strip(), body.config))


@router.delete("/{system_id}", status_code=204)
async def delete_system(project_id: str, system_id: str) -> Response:
    async with db.tx() as c:
        await c.execute("DELETE FROM external_systems WHERE id=? AND project_id=?", (system_id, project_id))
    return Response(status_code=204)


@router.post("/test")
async def test_system(project_id: str, body: TestIn) -> dict[str, Any]:
    """Send one question (default: the first of the newest eval set) and show what came back, so the mapping
    can be fixed before an eval. Nothing is saved."""
    await _project(project_id)
    question = body.question
    if question is None:
        row = await db.fetch_one(
            "SELECT i.question FROM eval_items i JOIN eval_sets s ON s.id = i.eval_set_id"
            " WHERE s.project_id=? AND i.valid=1 ORDER BY s.created_at DESC, i.ordinal LIMIT 1", (project_id,))
        question = row["question"] if row else SAMPLE_QUESTION
    try:
        got = await external.query(body.config, question)
    except external.ExternalError as e:
        raise HTTPException(502, str(e)) from e
    return {"question": question, "ms": round(got["ms"], 1), "answer": got["answer"],
            "contexts": [{**c, "text": c["text"][:300]} for c in got["contexts"]]}
