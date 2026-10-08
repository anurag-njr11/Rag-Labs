"""Data tables and attested computations (FR-3.21)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError

from .. import db
from ..engine import compute
from ..engine.compute import Computation, ComputeError

router = APIRouter(prefix="/api/projects/{project_id}", tags=["compute"])


async def _project(project_id: str) -> None:
    if not await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(404, "project not found")


@router.get("/data")
async def list_tables(project_id: str) -> list[dict[str, Any]]:
    await _project(project_id)
    return await asyncio.to_thread(compute.tables, project_id)


@router.post("/data", status_code=201)
async def upload_tables(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Load CSV files as tables (a file replaces the table of the same name)."""
    await _project(project_id)
    created, errors = [], []
    for f in files:
        name = f.filename or "data.csv"
        if not name.lower().endswith((".csv", ".tsv", ".txt")):
            errors.append({"filename": name, "error": "only CSV / TSV files can be data tables"})
            continue
        try:
            created.append(await asyncio.to_thread(compute.import_csv, project_id, name, await f.read()))
        except ComputeError as e:
            errors.append({"filename": name, "error": str(e)})
    return {"created": created, "errors": errors}


@router.delete("/data/{table}", status_code=204)
async def delete_table(project_id: str, table: str) -> None:
    await _project(project_id)
    if not await asyncio.to_thread(compute.drop_table, project_id, table):
        raise HTTPException(404, "table not found")


def _out(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], **db.loads(row["spec"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}


async def _checked(project_id: str, body: dict[str, Any]) -> Computation:
    try:
        comp = Computation.model_validate(body)
        await asyncio.to_thread(compute.check_sql, project_id, comp)
    except ValidationError as e:
        raise HTTPException(422, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from e
    except ComputeError as e:
        raise HTTPException(422, str(e)) from e
    return comp


@router.get("/computations")
async def list_computations(project_id: str) -> list[dict[str, Any]]:
    await _project(project_id)
    rows = await db.fetch_all("SELECT * FROM computations WHERE project_id=? ORDER BY created_at, id", (project_id,))
    return [_out(r) for r in rows]


@router.post("/computations", status_code=201)
async def create_computation(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    await _project(project_id)
    comp = await _checked(project_id, body)
    cid, now = db.new_id(), db.now_iso()
    async with db.tx() as c:
        await c.execute("INSERT INTO computations (id, project_id, spec, created_at, updated_at) VALUES (?,?,?,?,?)",
                        (cid, project_id, db.dumps(comp.model_dump(mode="json")), now, now))
    return _out(await db.fetch_one("SELECT * FROM computations WHERE id=?", (cid,)))


async def _get(project_id: str, cid: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM computations WHERE id=? AND project_id=?", (cid, project_id))
    if row is None:
        raise HTTPException(404, "computation not found")
    return row


@router.put("/computations/{cid}")
async def update_computation(project_id: str, cid: str, body: dict[str, Any]) -> dict[str, Any]:
    await _get(project_id, cid)
    comp = await _checked(project_id, body)
    async with db.tx() as c:
        await c.execute("UPDATE computations SET spec=?, updated_at=? WHERE id=?",
                        (db.dumps(comp.model_dump(mode="json")), db.now_iso(), cid))
    return _out(await _get(project_id, cid))


@router.delete("/computations/{cid}", status_code=204)
async def delete_computation(project_id: str, cid: str) -> None:
    await _get(project_id, cid)
    async with db.tx() as c:
        await c.execute("DELETE FROM computations WHERE id=?", (cid,))


class RunIn(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.post("/computations/{cid}/run")
async def run_computation(project_id: str, cid: str, body: RunIn) -> dict[str, Any]:
    """Try a computation with given values: the same coerce → read-only execute → attest as chat."""
    comp = Computation.model_validate(db.loads((await _get(project_id, cid))["spec"]))
    try:
        return await compute.run_checked(project_id, comp, body.parameters)
    except ComputeError as e:
        raise HTTPException(422, str(e)) from e
