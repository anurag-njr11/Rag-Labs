"""API keys and the usage dashboard (FR-3.23)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from .. import access, db

router = APIRouter(prefix="/api", tags=["access"])


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["chat", "admin"] = "chat"
    project_id: str | None = None  # required for a chat key

    @model_validator(mode="after")
    def _project(self) -> KeyIn:
        if self.scope == "chat" and not self.project_id:
            raise ValueError("a chat key belongs to one project: set project_id")
        if self.scope == "admin":
            self.project_id = None
        return self


@router.get("/keys")
async def list_keys() -> list[dict[str, Any]]:
    return await access.list_keys()


@router.post("/keys", status_code=201)
async def create_key(body: KeyIn) -> dict[str, Any]:
    """The response is the only time the key itself is shown; only its hash is stored."""
    if body.project_id and not await db.fetch_one("SELECT id FROM projects WHERE id=?", (body.project_id,)):
        raise HTTPException(404, "project not found")
    return await access.create_key(body.name, body.scope, body.project_id)


@router.delete("/keys/{kid}", status_code=204)
async def revoke_key(kid: str) -> None:
    if not await access.revoke(kid):
        raise HTTPException(404, "key not found or already revoked")


@router.get("/projects/{project_id}/usage")
async def usage(project_id: str, days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")
    return await access.usage(project_id, days)
