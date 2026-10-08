from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .. import db
from ..core.pipeline import diff_pipelines
from ..engine import adapter, evaluate, external, injection, prompt_opt, sweep, sync
from ..ingest import jobs
from ..llm import provider as llm

router = APIRouter(prefix="/api/projects/{project_id}/eval", tags=["eval"])


class EvalSetIn(BaseModel):
    size: int = Field(30, ge=5, le=100)
    version_id: str | None = None


class ItemIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    gold_answer: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=4000)
    document_id: str
    facets: list[str] = Field(default_factory=list, max_length=8)  # required facts (FR-2.6)
    tests: str | None = Field(None, max_length=8000)  # Python asserts for the answer's code (FR-3.17)


class ItemPatch(BaseModel):
    question: str | None = Field(None, min_length=3, max_length=1000)
    gold_answer: str | None = Field(None, min_length=1, max_length=2000)
    evidence: str | None = Field(None, min_length=1, max_length=4000)
    facets: list[str] | None = Field(None, max_length=8)
    tests: str | None = Field(None, max_length=8000)  # "" clears them
    valid: bool | None = None  # restore a rejected item / drop a kept one


class CsvIn(BaseModel):
    csv: str = Field(max_length=2_000_000)


CSV_COLUMNS = ["question", "gold_answer", "evidence", "document", "valid", "reject_reason", "facets", "tests"]
MAX_ITEMS = 500  # valid questions per set, for hand adds, restores and CSV import
_FORMULA = ("=", "+", "-", "@")  # a spreadsheet would run a cell starting with one of these


def _csv_safe(v: Any) -> Any:
    return f"'{v}" if isinstance(v, str) and v.startswith(_FORMULA) else v


def _csv_unsafe(v: str) -> str:
    return v[1:] if v.startswith("'") and v[1:].startswith(_FORMULA) else v


class JudgeIn(BaseModel):
    """Answer grader (FOLLOW_UPS #2): any configured provider/model; omitted = the version's own."""
    provider: str
    model: str = ""

    def checked(self) -> dict[str, str]:
        if self.provider not in llm.PROVIDERS:
            raise HTTPException(422, f"Unknown judge provider {self.provider!r}.")
        return self.model_dump()


class EvalRunIn(BaseModel):
    version_id: str | None = None
    answers: bool = False  # also generate + LLM-grade each answer
    judge: JudgeIn | None = None


class AdapterIn(BaseModel):
    set_id: str
    version_id: str | None = None  # its embedder and index are what the adapter is trained for


class InjectionIn(BaseModel):
    set_id: str
    version_id: str | None = None
    questions: int = Field(5, ge=1, le=20)  # × 5 payloads × variants = LLM calls
    compare: bool = True  # also run every defence variant (FR-3.8)


class AxisIn(BaseModel):
    path: str = Field(pattern=r"^[a-z_]+\.[a-z_]+$")
    values: list[Any] = Field(min_length=1, max_length=12)


class SweepIn(BaseModel):
    set_id: str
    version_id: str | None = None
    axes: list[AxisIn] = Field(min_length=1, max_length=4)
    # Successive halving: answer-grade the top 25% of cells by retrieval (at most 5) after scoring all.
    auto_optimize: bool = False
    judge: JudgeIn | None = None


async def _version(project_id: str, version_id: str | None) -> dict[str, Any]:
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


async def _set(project_id: str, set_id: str) -> dict[str, Any]:
    s = await db.fetch_one("SELECT * FROM eval_sets WHERE id=? AND project_id=?", (set_id, project_id))
    if s is None:
        raise HTTPException(404, "eval set not found")
    return s


def _set_out(s: dict[str, Any], corpus_sha: str | None = None) -> dict[str, Any]:
    # corpus_changed: the project's documents differ from the ones the set was generated from
    # (None for sets generated before this was recorded).
    changed = None if not s.get("corpus_sha") or corpus_sha is None else s["corpus_sha"] != corpus_sha
    return {**s, "stats": db.loads(s["stats"], {}), "corpus_changed": changed}


def _item_out(i: dict[str, Any]) -> dict[str, Any]:
    return {**i, "valid": bool(i["valid"]), "facets": db.loads(i.get("facets"), []) or []}


_BUMP = "UPDATE eval_sets SET revision = revision + 1 WHERE id=?"  # FR-2.5: every edit is a new revision


def _facets(raw: list[str] | None) -> str | None:
    return None if raw is None else db.dumps(evaluate.clean_facets(raw))


def _run_out(r: dict[str, Any], full: bool = False) -> dict[str, Any]:
    out = {k: r[k] for k in ("id", "eval_set_id", "version_id", "build_id", "status", "error", "created_at",
                             "set_revision")}
    out["version"] = r.get("version")
    out["external"] = r.get("external_name")  # a bring-your-own RAG's name (version_id is its id)
    out["metrics"] = db.loads(r["metrics"], None)
    if full:
        out["results"] = db.loads(r["results"], [])
    return out


@router.post("/sets", status_code=201)
async def create_set(project_id: str, body: EvalSetIn) -> dict[str, Any]:
    v = await _version(project_id, body.version_id)
    docs = await db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE project_id=?", (project_id,))
    if not docs or docs["n"] == 0:
        raise HTTPException(409, "Add documents before generating an eval set.")
    set_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_sets (id, project_id, version_id, size_requested, created_at)"
                        " VALUES (?,?,?,?,?)", (set_id, project_id, v["id"], body.size, db.now_iso()))
    job = jobs.start("evalset", project_id,
                     lambda job: evaluate.generate_set(job, set_id, project_id, v, body.size))
    return {"eval_set": _set_out(await _set(project_id, set_id)), "job_id": job.id}


@router.get("/sets")
async def list_sets(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM eval_sets WHERE project_id=? ORDER BY created_at DESC, rowid DESC",
                              (project_id,))
    sha = await evaluate.corpus_sha(project_id)
    return [_set_out(r, sha) for r in rows]


@router.get("/sets/{set_id}")
async def get_set(project_id: str, set_id: str) -> dict[str, Any]:
    s = _set_out(await _set(project_id, set_id), await evaluate.corpus_sha(project_id))
    items = await db.fetch_all(
        "SELECT i.*, d.filename AS document FROM eval_items i LEFT JOIN documents d ON d.id = i.document_id"
        " WHERE i.eval_set_id=? ORDER BY i.ordinal", (set_id,))
    s["items"] = [_item_out(i) for i in items]
    return s


# --- hand edits (FR-2.4) ----------------------------------------------------------
# Runs keep their per-item results; a run scored before an edit used the old questions.

async def _item(set_id: str, item_id: str) -> dict[str, Any]:
    it = await db.fetch_one("SELECT * FROM eval_items WHERE id=? AND eval_set_id=?", (item_id, set_id))
    if it is None:
        raise HTTPException(404, "item not found")
    return it


async def _add_item(s: dict[str, Any], body: ItemIn) -> str:
    doc = await db.fetch_one("SELECT id FROM documents WHERE id=? AND project_id=?", (body.document_id, s["project_id"]))
    if doc is None:
        raise HTTPException(422, "Unknown document.")
    if await _room(s["id"]) <= 0:
        raise HTTPException(409, f"An eval set holds at most {MAX_ITEMS} questions.")
    reason = await evaluate.check_evidence(s["build_id"], body.document_id, body.evidence)
    if reason:
        raise HTTPException(422, reason)
    item_id = db.new_id()
    async with db.tx() as c:
        row = await (await c.execute("SELECT COALESCE(MAX(ordinal), -1) + 1 FROM eval_items WHERE eval_set_id=?",
                                     (s["id"],))).fetchone()
        await c.execute(
            "INSERT INTO eval_items (id, eval_set_id, ordinal, question, gold_answer, evidence, document_id,"
            " gold_chunk_id, valid, facets, tests) VALUES (?,?,?,?,?,?,?,'',1,?,?)",
            (item_id, s["id"], row[0], body.question.strip(), body.gold_answer.strip(), body.evidence.strip(),
             body.document_id, _facets(body.facets), (body.tests or "").strip() or None))
        await c.execute(_BUMP, (s["id"],))
    return item_id


async def _room(set_id: str) -> int:
    row = await db.fetch_one("SELECT COUNT(*) AS n FROM eval_items WHERE eval_set_id=? AND valid=1", (set_id,))
    return MAX_ITEMS - row["n"]


@router.post("/sets/{set_id}/items", status_code=201)
async def add_item(project_id: str, set_id: str, body: ItemIn) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    return _item_out(await _item(set_id, await _add_item(s, body)))


@router.patch("/sets/{set_id}/items/{item_id}")
async def update_item(project_id: str, set_id: str, item_id: str, body: ItemPatch) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    it = await _item(set_id, item_id)
    changes = body.model_dump(exclude_none=True)
    if changes.get("evidence") == it["evidence"]:
        del changes["evidence"]  # unchanged (the edit form sends every field): nothing to re-check
    if "evidence" in changes:
        reason = await evaluate.check_evidence(s["build_id"], it["document_id"], changes["evidence"])
        if reason:
            raise HTTPException(422, reason)
    if changes.get("valid") is True and not it["valid"] and await _room(set_id) <= 0:
        raise HTTPException(409, f"An eval set holds at most {MAX_ITEMS} questions.")
    if changes.get("valid") is True and "evidence" not in changes:
        reason = await evaluate.check_evidence(s["build_id"], it["document_id"], it["evidence"])
        if reason:
            raise HTTPException(422, f"Can't restore it: {reason}")
    if "facets" in changes:
        changes["facets"] = _facets(changes["facets"])
    if "tests" in changes:
        changes["tests"] = changes["tests"].strip() or None
    if "valid" in changes:
        changes["valid"] = int(changes["valid"])
        if changes["valid"]:
            changes["reject_reason"] = None
        else:
            changes.setdefault("reject_reason", "removed by hand")
    if changes:
        cols = ", ".join(f"{k}=?" for k in changes)
        async with db.tx() as c:
            await c.execute(f"UPDATE eval_items SET {cols} WHERE id=?", (*changes.values(), item_id))
            await c.execute(_BUMP, (set_id,))
    return _item_out(await _item(set_id, item_id))


@router.delete("/sets/{set_id}/items/{item_id}", status_code=204)
async def delete_item(project_id: str, set_id: str, item_id: str) -> None:
    await _set(project_id, set_id)
    await _item(set_id, item_id)
    async with db.tx() as c:
        await c.execute("DELETE FROM eval_items WHERE id=?", (item_id,))
        await c.execute(_BUMP, (set_id,))


@router.get("/sets/{set_id}/export.csv")
async def export_csv(project_id: str, set_id: str) -> Response:
    await _set(project_id, set_id)
    items = await db.fetch_all(
        "SELECT i.*, d.filename AS document FROM eval_items i LEFT JOIN documents d ON d.id = i.document_id"
        " WHERE i.eval_set_id=? ORDER BY i.ordinal", (set_id,))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for i in items:
        row = {**i, "valid": "yes" if i["valid"] else "no", "reject_reason": i["reject_reason"] or "",
               "facets": " | ".join(db.loads(i["facets"], []) or []), "tests": i.get("tests") or ""}
        w.writerow({k: _csv_safe(row[k]) for k in CSV_COLUMNS})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="eval-set-{set_id[:8]}.csv"'})


@router.post("/sets/{set_id}/import")
async def import_csv(project_id: str, set_id: str, body: CsvIn) -> dict[str, Any]:
    """Add rows from a CSV with columns question, gold_answer (or answer), evidence, document
    (the filename), and optionally facets (`|`-separated required facts). Rows marked valid=no are
    skipped. Each row is checked like a hand-added item."""
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    reader = csv.DictReader(io.StringIO(body.csv.lstrip("\ufeff")))
    cols = {c.strip().lower() for c in reader.fieldnames or []}
    if not {"question", "evidence", "document"} <= cols or not {"gold_answer", "answer"} & cols:
        raise HTTPException(422, "The CSV needs columns: question, gold_answer (or answer), evidence, document.")
    docs = {d["filename"]: d["id"] for d in await db.fetch_all(
        "SELECT id, filename FROM documents WHERE project_id=?", (project_id,))}
    added, skipped, errors = 0, 0, []
    room = await _room(set_id)
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): _csv_unsafe((v or "").strip()) for k, v in raw.items()}
        if row.get("valid", "yes").lower() in ("no", "false", "0"):
            continue
        if added >= room:
            skipped += 1  # over MAX_ITEMS
            continue
        doc_id = docs.get(row.get("document", ""))
        if doc_id is None:
            errors.append({"row": n, "message": f"No document named {row.get('document')!r} in this project."})
            continue
        try:
            body_in = ItemIn(question=row.get("question", ""), gold_answer=row.get("gold_answer") or row.get("answer", ""),
                             evidence=row.get("evidence", ""), document_id=doc_id,
                             facets=[f for f in row.get("facets", "").split("|") if f.strip()],
                             tests=row.get("tests") or None)
            await _add_item(s, body_in)
            added += 1
        except HTTPException as e:
            errors.append({"row": n, "message": str(e.detail)})
        except ValueError as e:  # pydantic validation
            errors.append({"row": n, "message": str(e).splitlines()[-1].strip() or "Invalid row."})
    return {"added": added, "skipped": skipped, "errors": errors[:50], "error_count": len(errors)}


@router.post("/sets/{set_id}/runs", status_code=201)
async def create_run(project_id: str, set_id: str, body: EvalRunIn) -> dict[str, Any]:
    s = await _set(project_id, set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    if body.version_id and (system := await external.get(project_id, body.version_id)):
        v = {"id": system["id"], "config": db.dumps({"external": system["config"].model_dump()})}  # never stored
    else:
        v = await _version(project_id, body.version_id)
    judge = body.judge.checked() if body.judge else None
    run_id, job_id = await start_run(project_id, set_id, v, body.answers, judge)
    return {"run": await _get_run(project_id, run_id), "job_id": job_id}


async def start_run(project_id: str, set_id: str, v: dict[str, Any], answers: bool = False,
                    judge: dict[str, str] | None = None) -> tuple[str, str]:
    run_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO eval_runs (id, eval_set_id, project_id, version_id, created_at)"
                        " VALUES (?,?,?,?,?)", (run_id, set_id, project_id, v["id"], db.now_iso()))
    job = jobs.start("eval", project_id,
                     lambda job: evaluate.run_eval(job, run_id, project_id, set_id, v, answers, judge))
    return run_id, job.id


async def regression_check(project_id: str, v: dict[str, Any]) -> str | None:
    """Regression guard: score a newly saved version on the newest ready eval set.
    Returns the eval job id, or None when the project has no ready set."""
    s = await db.fetch_one("SELECT id FROM eval_sets WHERE project_id=? AND status='ready'"
                           " ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id,))
    if s is None:
        return None
    return (await start_run(project_id, s["id"], v))[1]


async def _get_run(project_id: str, run_id: str, full: bool = False) -> dict[str, Any]:
    r = await db.fetch_one(
        "SELECT r.*, v.version, e.name AS external_name FROM eval_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
           " LEFT JOIN external_systems e ON e.id = r.version_id"
        " WHERE r.id=? AND r.project_id=?", (run_id, project_id))
    if r is None:
        raise HTTPException(404, "eval run not found")
    return _run_out(r, full)


def _adapter_out(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: r[k] for k in ("id", "version_id", "eval_set_id", "status", "error", "created_at", "embed_key", "dim")}
    out.update(version=r.get("version"), metrics=db.loads(r["metrics"]))
    return out


async def _get_adapter(project_id: str, adapter_id: str) -> dict[str, Any]:
    r = await db.fetch_one(
        "SELECT a.*, v.version FROM adapters a LEFT JOIN pipeline_versions v ON v.id = a.version_id"
        " WHERE a.id=? AND a.project_id=?", (adapter_id, project_id))
    if r is None:
        raise HTTPException(404, "adapter not found")
    return _adapter_out(r)


@router.post("/adapters", status_code=201)
async def create_adapter(project_id: str, body: AdapterIn) -> dict[str, Any]:
    """Train a query-side embedding adapter on an eval set's labels (FR-3.10)."""
    s = await _set(project_id, body.set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    adapter_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO adapters (id, project_id, version_id, eval_set_id, created_at) VALUES (?,?,?,?,?)",
                        (adapter_id, project_id, v["id"], s["id"], db.now_iso()))
    job = jobs.start("adapter", project_id, lambda job: adapter.train(job, adapter_id, project_id, v, s["id"]))
    return {"adapter": await _get_adapter(project_id, adapter_id), "job_id": job.id}


@router.get("/adapters")
async def list_adapters(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT a.*, v.version FROM adapters a LEFT JOIN pipeline_versions v ON v.id = a.version_id"
        " WHERE a.project_id=? ORDER BY a.created_at DESC, a.rowid DESC", (project_id,))
    return [_adapter_out(r) for r in rows]


@router.get("/adapters/{adapter_id}")
async def get_adapter(project_id: str, adapter_id: str) -> dict[str, Any]:
    return await _get_adapter(project_id, adapter_id)


@router.delete("/adapters/{adapter_id}", status_code=204)
async def delete_adapter(project_id: str, adapter_id: str) -> None:
    """Versions that still name it skip it from then on (their trace says so)."""
    await _get_adapter(project_id, adapter_id)
    async with db.tx() as c:
        await c.execute("DELETE FROM adapters WHERE id=?", (adapter_id,))
    adapter.adapter_path(project_id, adapter_id).unlink(missing_ok=True)
    adapter._loaded.pop(f"{project_id}/{adapter_id}", None)


def _prompt_run_out(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: r[k] for k in ("id", "version_id", "eval_set_id", "status", "error", "created_at")}
    out.update(version=r.get("version"), result=db.loads(r["result"]))
    return out


async def _get_prompt_run(project_id: str, run_id: str) -> dict[str, Any]:
    r = await db.fetch_one(
        "SELECT r.*, v.version FROM prompt_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
        " WHERE r.id=? AND r.project_id=?", (run_id, project_id))
    if r is None:
        raise HTTPException(404, "prompt optimisation run not found")
    return _prompt_run_out(r)


@router.post("/prompt-runs", status_code=201)
async def create_prompt_run(project_id: str, body: AdapterIn) -> dict[str, Any]:
    """Optimise the prompt's instructions and examples against an eval set (FR-3.11)."""
    s = await _set(project_id, body.set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    run_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO prompt_runs (id, project_id, version_id, eval_set_id, created_at) VALUES (?,?,?,?,?)",
                        (run_id, project_id, v["id"], s["id"], db.now_iso()))
    job = jobs.start("prompt", project_id, lambda job: prompt_opt.run(job, run_id, project_id, v, s["id"]))
    return {"run": await _get_prompt_run(project_id, run_id), "job_id": job.id}


@router.get("/prompt-runs")
async def list_prompt_runs(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT r.*, v.version FROM prompt_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
        " WHERE r.project_id=? ORDER BY r.created_at DESC, r.rowid DESC", (project_id,))
    return [_prompt_run_out(r) for r in rows]


@router.get("/prompt-runs/{run_id}")
async def get_prompt_run(project_id: str, run_id: str) -> dict[str, Any]:
    return await _get_prompt_run(project_id, run_id)


def _injection_out(r: dict[str, Any], full: bool = False) -> dict[str, Any]:
    out = {k: r[k] for k in ("id", "version_id", "eval_set_id", "status", "error", "created_at")}
    out.update(version=r.get("version"), options=db.loads(r["options"], {}), metrics=db.loads(r["metrics"]))
    if full:
        out["results"] = db.loads(r["results"], [])
    return out


@router.post("/injection", status_code=201)
async def create_injection_run(project_id: str, body: InjectionIn) -> dict[str, Any]:
    """Injection-resistance test (FR-3.7/3.8): canary payloads in retrieval, scored per defence variant."""
    s = await _set(project_id, body.set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    run_id = db.new_id()
    options = {"questions": body.questions, "compare": body.compare}
    async with db.tx() as c:
        await c.execute("INSERT INTO injection_runs (id, project_id, version_id, eval_set_id, options, created_at)"
                        " VALUES (?,?,?,?,?,?)", (run_id, project_id, v["id"], s["id"], db.dumps(options),
                                                  db.now_iso()))
    job = jobs.start("injection", project_id, lambda job: injection.run(
        job, run_id, project_id, v, s["id"], body.questions, body.compare))
    return {"run": await _get_injection(project_id, run_id), "job_id": job.id}


async def _get_injection(project_id: str, run_id: str, full: bool = False) -> dict[str, Any]:
    r = await db.fetch_one(
        "SELECT r.*, v.version FROM injection_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
        " WHERE r.id=? AND r.project_id=?", (run_id, project_id))
    if r is None:
        raise HTTPException(404, "injection run not found")
    return _injection_out(r, full)


@router.get("/injection")
async def list_injection_runs(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT r.*, v.version FROM injection_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
        " WHERE r.project_id=? ORDER BY r.created_at DESC, r.rowid DESC", (project_id,))
    return [_injection_out(r) for r in rows]


@router.get("/injection/{run_id}")
async def get_injection_run(project_id: str, run_id: str) -> dict[str, Any]:
    return await _get_injection(project_id, run_id, full=True)


@router.get("/runs")
async def list_runs(project_id: str, set_id: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT r.*, v.version, e.name AS external_name FROM eval_runs r LEFT JOIN pipeline_versions v ON v.id = r.version_id"
           " LEFT JOIN external_systems e ON e.id = r.version_id"
           " WHERE r.project_id=?")
    params: tuple = (project_id,)
    if set_id:
        sql += " AND r.eval_set_id=?"
        params += (set_id,)
    rows = await db.fetch_all(sql + " ORDER BY r.created_at, r.rowid", params)
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(project_id: str, run_id: str) -> dict[str, Any]:
    return await _get_run(project_id, run_id, full=True)


@router.get("/runs/{run_id}/fixes")
async def run_fixes(project_id: str, run_id: str) -> list[dict[str, Any]]:
    """One-click fixes for the run's miss diagnoses: each a full config to save as a new version."""
    run = await _get_run(project_id, run_id, full=True)
    if run["external"]:
        return []  # nothing of ours to change in someone else's RAG
    v = await _version(project_id, run["version_id"])
    cfg = sync.version_config(v)
    out = []
    for diagnosis in evaluate.DIAGNOSES:
        new = evaluate.suggest_fix(cfg, diagnosis, run["results"])
        if new is not None:
            out.append({"diagnosis": diagnosis, "config": new, "changes": diff_pipelines(cfg, new),
                        "base_version": run["version"]})
    return out


# --- sweeps -------------------------------------------------------------------

def _sweep_out(s: dict[str, Any]) -> dict[str, Any]:
    cells = db.loads(s["cells"], [])
    counts: dict[str, int] = {}
    for c in cells:
        if s["status"] != "running" and c["status"] in ("pending", "running"):
            c["status"] = "skipped"  # the sweep stopped (cancel, failure, restart) before this cell finished
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {**s, "axes": db.loads(s["axes"], []), "cells": cells, "counts": counts}


async def _sweep(project_id: str, sweep_id: str) -> dict[str, Any]:
    s = await db.fetch_one("SELECT s.*, v.version AS base_version FROM sweeps s LEFT JOIN pipeline_versions v"
                           " ON v.id = s.base_version_id WHERE s.id=? AND s.project_id=?", (sweep_id, project_id))
    if s is None:
        raise HTTPException(404, "sweep not found")
    return _sweep_out(s)


@router.get("/sweep-axes")
async def sweep_axes(project_id: str) -> dict[str, Any]:
    return {"axes": sweep.AXES, "max_cells": sweep.MAX_CELLS}


@router.post("/sweeps", status_code=201)
async def create_sweep(project_id: str, body: SweepIn) -> dict[str, Any]:
    s = await _set(project_id, body.set_id)
    if s["status"] != "ready":
        raise HTTPException(409, "This eval set isn't ready yet.")
    v = await _version(project_id, body.version_id)
    judge = body.judge.checked() if body.judge else None
    axes = [a.model_dump() for a in body.axes]
    try:
        cells = sweep.expand_grid(sync.version_config(v), axes)
    except sweep.SweepError as e:
        raise HTTPException(422, str(e)) from e
    sweep_id = db.new_id()
    async with db.tx() as c:
        await c.execute("INSERT INTO sweeps (id, project_id, eval_set_id, base_version_id, axes, cells, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", (sweep_id, project_id, s["id"], v["id"], db.dumps(axes),
                                                    db.dumps(cells), db.now_iso()))
    job = jobs.start("sweep", project_id, lambda job: sweep.run_sweep(job, sweep_id, body.auto_optimize, judge))
    return {"sweep": await _sweep(project_id, sweep_id), "job_id": job.id}


@router.get("/sweeps")
async def list_sweeps(project_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT s.*, v.version AS base_version FROM sweeps s LEFT JOIN pipeline_versions v"
                              " ON v.id = s.base_version_id WHERE s.project_id=?"
                              " ORDER BY s.created_at DESC, s.rowid DESC", (project_id,))
    return [_sweep_out(r) for r in rows]


@router.get("/sweeps/{sweep_id}")
async def get_sweep(project_id: str, sweep_id: str) -> dict[str, Any]:
    return await _sweep(project_id, sweep_id)


@router.post("/sweeps/{sweep_id}/cancel")
async def cancel_sweep(project_id: str, sweep_id: str) -> dict[str, Any]:
    await _sweep(project_id, sweep_id)
    async with db.tx() as c:
        await c.execute("UPDATE sweeps SET status='cancelled' WHERE id=? AND status='running'", (sweep_id,))
    return await _sweep(project_id, sweep_id)
