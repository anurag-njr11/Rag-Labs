"""Recipe gallery (FR-3.26)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..core.pipeline import PipelineError, validate_pipeline, with_defaults
from ..engine import recipes, sync

router = APIRouter(prefix="/api", tags=["recipes"])


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=600)
    tags: list[str] = Field(default_factory=list, max_length=8)
    config: dict[str, Any]
    source_project: str | None = None


class ForkIn(BaseModel):
    config: dict[str, Any]


@router.get("/recipes")
async def list_recipes() -> list[dict[str, Any]]:
    return [*(await recipes.saved()), *recipes.builtin()]


@router.post("/recipes", status_code=201)
async def save_recipe(body: RecipeIn) -> dict[str, Any]:
    """Save a pipeline (from a version, or imported from a shared link) to the gallery."""
    try:
        cfg = validate_pipeline(with_defaults(body.config))
    except PipelineError as e:
        raise HTTPException(422, {"message": "That isn't a valid pipeline", "errors": e.errors}) from e
    cfg["retrieve"]["adapter"] = ""  # corpus-specific: never part of a recipe
    rid = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO recipes (id, name, description, tags, config, source_project, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", (rid, body.name, body.description, db.dumps(body.tags[:8]),
                                                    db.dumps(cfg), body.source_project, db.now_iso()))
    return next(r for r in await recipes.saved() if r["id"] == rid)


@router.delete("/recipes/{rid}", status_code=204)
async def delete_recipe(rid: str) -> None:
    if rid.startswith("builtin-"):
        raise HTTPException(409, "Built-in recipes can't be deleted.")
    async with db.tx() as c:
        cur = await c.execute("DELETE FROM recipes WHERE id=?", (rid,))
        if not cur.rowcount:
            raise HTTPException(404, "recipe not found")


@router.post("/projects/{project_id}/recipe-config")
async def fork_config(project_id: str, body: ForkIn) -> dict[str, Any]:
    """A recipe's config made fit for this project (adapter dropped, unconnected LLM replaced) + what
    changed. The UI then saves it as a version the usual way."""
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")
    active = await sync.active_version(project_id)
    target = with_defaults(db.loads(active["config"])) if active else None
    try:
        cfg, notes = recipes.portable(body.config, target)
    except PipelineError as e:
        raise HTTPException(422, {"message": "That isn't a valid pipeline", "errors": e.errors}) from e
    return {"config": cfg, "notes": notes}
