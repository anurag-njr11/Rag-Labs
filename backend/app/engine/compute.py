"""Attested Computation (FR-3.21): numbers come from sanctioned computations, prose from retrieval.

A computed value ("Q3 revenue", "active users in region X") shouldn't be fished out of a document —
the slide it lives on may be stale. Instead a project defines *computations*: a parameterised,
read-only SQL query over its data tables, plus an *attester* — deterministic checks the result must
pass before anyone sees it. At question time the model may only pick a computation and supply
parameter values; it can never author the query. Values are type-checked, the query runs on a
read-only connection with a time limit, the result is attested, and the answer is rendered from the
result without an LLM rewriting the number. A receipt (SQL, parameters, result, checks) goes with it.

Departure from OKF v0.2: its attester is a Python file. Running Python that arrived with a project is
arbitrary code execution, so attesters here are declarative checks (rows, columns, non-null, bounds).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import get_settings

MAX_CSV_MB = 50
MAX_ROWS_IMPORT = 200_000
MAX_RESULT_ROWS = 200
TIMEOUT_S = 2.0
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_PARAM = re.compile(r"(?<!:):([A-Za-z_]\w*)")


class ComputeError(ValueError):
    pass


# --- data tables -------------------------------------------------------------------


def db_path(project_id: str) -> Path:
    return get_settings().data_dir / "compute" / f"{project_id}.db"


def table_name(filename: str) -> str:
    stem = re.sub(r"[^a-z0-9_]+", "_", Path(filename).stem.lower()).strip("_") or "data"
    return (stem if stem[0].isalpha() else f"t_{stem}")[:63]


def _column(name: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_") or "col"
    base = base if base[0].isalpha() else f"c_{base}"
    out, n = base[:63], 2
    while out in used:
        out, n = f"{base[:60]}_{n}", n + 1
    used.add(out)
    return out


def _affinity(values: list[str]) -> str:
    vals = [v for v in values if v.strip() != ""]
    if not vals:
        return "TEXT"
    try:
        for v in vals:
            int(v.replace(",", ""))
        return "INTEGER"
    except ValueError:
        pass
    try:
        for v in vals:
            float(v.replace(",", ""))
        return "REAL"
    except ValueError:
        return "TEXT"


def _convert(v: str, kind: str) -> Any:
    if v.strip() == "":
        return None
    if kind == "INTEGER":
        return int(v.replace(",", ""))
    if kind == "REAL":
        return float(v.replace(",", ""))
    return v


def import_csv(project_id: str, filename: str, data: bytes) -> dict[str, Any]:
    """Load a CSV as a table (replacing one of the same name). Column types are inferred."""
    if len(data) > MAX_CSV_MB * 1024 * 1024:
        raise ComputeError(f"{filename}: larger than {MAX_CSV_MB} MB.")
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if len(rows) < 2:
        raise ComputeError(f"{filename}: needs a header row and at least one data row.")
    if len(rows) - 1 > MAX_ROWS_IMPORT:
        raise ComputeError(f"{filename}: more than {MAX_ROWS_IMPORT:,} rows.")
    used: set[str] = set()
    cols = [_column(h, used) for h in rows[0]]
    body = [r + [""] * (len(cols) - len(r)) for r in rows[1:] if any(c.strip() for c in r)]
    kinds = [_affinity([r[i] for r in body]) for i in range(len(cols))]
    name = table_name(filename)
    path = db_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute(f'DROP TABLE IF EXISTS "{name}"')
        con.execute(f'CREATE TABLE "{name}" ({", ".join(f'"{c}" {k}' for c, k in zip(cols, kinds))})')
        con.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" * len(cols))})',
                        [[_convert(r[i], kinds[i]) for i in range(len(cols))] for r in body])
        con.commit()
    except ValueError as e:
        raise ComputeError(f"{filename}: {e}") from e
    finally:
        con.close()
    return {"table": name, "columns": [{"name": c, "type": k} for c, k in zip(cols, kinds)], "rows": len(body)}


def tables(project_id: str) -> list[dict[str, Any]]:
    path = db_path(project_id)
    if not path.exists():
        return []
    con = _readonly(path)
    try:
        out = []
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            cols = [{"name": r[1], "type": r[2]} for r in con.execute(f'PRAGMA table_info("{name}")')]
            n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            out.append({"table": name, "columns": cols, "rows": n})
        return out
    finally:
        con.close()


def drop_table(project_id: str, name: str) -> bool:
    path = db_path(project_id)
    if not path.exists() or not _NAME.match(name):
        return False
    con = sqlite3.connect(path)
    try:
        found = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if found:
            con.execute(f'DROP TABLE "{name}"')
            con.commit()
        return bool(found)
    finally:
        con.close()


def _readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    return con


# --- computations ----------------------------------------------------------------


class Parameter(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_]\w{0,40}$")
    type: Literal["integer", "number", "string", "date"] = "string"
    required: bool = True
    description: str = Field("", max_length=300)
    options: list[str] | None = Field(None, max_length=100)  # allowed values (strings)


class Attester(BaseModel):
    """Deterministic checks on the result. All must pass before the value is shown."""
    min_rows: int = Field(1, ge=0, le=MAX_RESULT_ROWS)
    max_rows: int = Field(1, ge=1, le=MAX_RESULT_ROWS)
    columns: list[str] = Field(default_factory=list, max_length=20)  # must be present, in this order
    non_null: bool = True
    bounds: dict[str, tuple[float | None, float | None]] = Field(default_factory=dict)  # column -> [min, max]

    @model_validator(mode="after")
    def _rows(self) -> Attester:
        if self.min_rows > self.max_rows:
            raise ValueError("min_rows can't exceed max_rows")
        return self


class Computation(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=600)  # what the router reads
    parameters: list[Parameter] = Field(default_factory=list, max_length=10)
    sql: str = Field(min_length=1, max_length=4000)
    attester: Attester = Field(default_factory=Attester)
    unit: str = Field("", max_length=40)  # shown after a single value, e.g. "USD"

    @field_validator("sql")
    @classmethod
    def _select_only(cls, v: str) -> str:
        s = v.strip().rstrip(";").strip()
        if ";" in s:
            raise ValueError("one statement only")
        if not re.match(r"^(select|with)\b", s, re.I):
            raise ValueError("must be a SELECT (or WITH … SELECT) query")
        return s

    @model_validator(mode="after")
    def _params_match(self) -> Computation:
        used = set(_PARAM.findall(self.sql))
        declared = {p.name for p in self.parameters}
        if used - declared:
            raise ValueError(f"the SQL uses undeclared parameters: {', '.join(sorted(used - declared))}")
        return self


def check_sql(project_id: str, comp: Computation) -> None:
    """Prepare the query against the data (read-only) so a typo fails when saving, not when asked."""
    path = db_path(project_id)
    if not path.exists():
        raise ComputeError("Upload a data table (CSV) first.")
    con = _readonly(path)
    try:
        con.execute(f"EXPLAIN {comp.sql}", {p.name: None for p in comp.parameters})
    except sqlite3.Error as e:
        raise ComputeError(f"SQL error: {e}") from e
    finally:
        con.close()


def coerce(comp: Computation, values: dict[str, Any]) -> dict[str, Any]:
    """Type-check parameter values supplied by the model (or a person). Unknown names are rejected."""
    extra = set(values) - {p.name for p in comp.parameters}
    if extra:
        raise ComputeError(f"unknown parameter(s): {', '.join(sorted(extra))}")
    out: dict[str, Any] = {}
    for p in comp.parameters:
        v = values.get(p.name)
        if v is None or v == "":
            if p.required:
                raise ComputeError(f"missing parameter {p.name}")
            out[p.name] = None
            continue
        try:
            if p.type == "integer":
                if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
                    raise ValueError
                v = int(v)
            elif p.type == "number":
                if isinstance(v, bool):
                    raise ValueError
                v = float(v)
            elif p.type == "date":
                v = date.fromisoformat(str(v)).isoformat()
            else:
                v = str(v)[:200]
        except (TypeError, ValueError):
            raise ComputeError(f"{p.name} must be a{'n' if p.type == 'integer' else ''} {p.type}") from None
        if p.options and str(v) not in p.options:
            raise ComputeError(f"{p.name} must be one of: {', '.join(p.options)}")
        out[p.name] = v
    return out


def execute(project_id: str, comp: Computation, params: dict[str, Any]) -> dict[str, Any]:
    """Run read-only with a time limit -> {columns, rows, ms, truncated}."""
    path = db_path(project_id)
    if not path.exists():
        raise ComputeError("This project has no data tables.")
    con = _readonly(path)
    deadline = time.perf_counter() + TIMEOUT_S
    con.set_progress_handler(lambda: int(time.perf_counter() > deadline), 10_000)
    t0 = time.perf_counter()
    try:
        cur = con.execute(comp.sql, params)
        rows = cur.fetchmany(MAX_RESULT_ROWS + 1)
        cols = [d[0] for d in cur.description or []]
    except sqlite3.OperationalError as e:
        raise ComputeError("the query took too long" if "interrupt" in str(e) else f"SQL error: {e}") from e
    except sqlite3.Error as e:
        raise ComputeError(f"SQL error: {e}") from e
    finally:
        con.close()
    return {"columns": cols, "rows": [list(r) for r in rows[:MAX_RESULT_ROWS]],
            "truncated": len(rows) > MAX_RESULT_ROWS, "ms": round((time.perf_counter() - t0) * 1000, 2)}


def attest(att: Attester, result: dict[str, Any]) -> list[dict[str, Any]]:
    """-> one {check, ok, detail} per rule; the value may be shown only if all are ok."""
    rows, cols = result["rows"], result["columns"]
    checks = [{"check": "rows", "ok": att.min_rows <= len(rows) <= att.max_rows and not result["truncated"],
               "detail": f"{len(rows)} row(s), expected {att.min_rows}–{att.max_rows}"}]
    if att.columns:
        checks.append({"check": "columns", "ok": cols[:len(att.columns)] == att.columns,
                       "detail": f"got {', '.join(cols)}"})
    if att.non_null:
        nulls = sum(v is None for r in rows for v in r)
        checks.append({"check": "non_null", "ok": nulls == 0, "detail": f"{nulls} empty value(s)"})
    for col, (lo, hi) in att.bounds.items():
        if col not in cols:
            checks.append({"check": f"bounds:{col}", "ok": False, "detail": "column missing"})
            continue
        i = cols.index(col)
        bad = [r[i] for r in rows if not isinstance(r[i], (int, float)) or (lo is not None and r[i] < lo)
               or (hi is not None and r[i] > hi)]
        checks.append({"check": f"bounds:{col}", "ok": not bad,
                       "detail": f"all within [{lo if lo is not None else '−∞'}, {hi if hi is not None else '∞'}]"
                       if not bad else f"out of range: {bad[:3]}"})
    return checks


def render(comp: Computation, params: dict[str, Any], result: dict[str, Any]) -> str:
    """The answer, deterministically from the result — no model rewrites the number."""
    shown = ", ".join(f"{k} = {v}" for k, v in params.items() if v is not None)
    head = f"**{comp.name}**" + (f" ({shown})" if shown else "")
    rows, cols = result["rows"], result["columns"]
    if len(rows) == 1 and len(cols) == 1:
        v = rows[0][0]
        value = f"{v:,}" if isinstance(v, int) else (f"{v:,.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
        return f"{head}: **{value}{(' ' + comp.unit) if comp.unit else ''}**"
    table = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    table += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:50]]
    more = f"\n\n…and {len(rows) - 50} more rows." if len(rows) > 50 else ""
    return f"{head}:\n\n" + "\n".join(table) + more


ROUTE_PROMPT = """You route questions for an assistant that can run these sanctioned computations over the
organisation's data. You never write queries; you only pick one and fill in its parameters.

Computations:
{catalog}

If the question asks for a value one of them computes, reply with JSON:
{{"computation": "<id>", "parameters": {{"<name>": <value>}}}}
Use exactly the parameter names listed; dates as YYYY-MM-DD. If none fits, or a required value isn't
given in the question, reply {{"computation": null}}. JSON only.

Question: {question}"""


def catalog_text(comps: list[tuple[str, Computation]]) -> str:
    lines = []
    for cid, c in comps:
        ps = "; ".join(f"{p.name} ({p.type}{', required' if p.required else ''}"
                       f"{', one of ' + '/'.join(p.options) if p.options else ''}){': ' + p.description if p.description else ''}"
                       for p in c.parameters) or "none"
        lines.append(f"- id: {cid}\n  name: {c.name}\n  computes: {c.description}\n  parameters: {ps}")
    return "\n".join(lines)


def parse_route(text: str) -> tuple[str | None, dict[str, Any]]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        d = json.loads(m.group(0) if m else text)
    except (ValueError, AttributeError):
        return None, {}
    if not isinstance(d, dict) or not isinstance(d.get("computation"), str):
        return None, {}
    params = d.get("parameters") if isinstance(d.get("parameters"), dict) else {}
    return d["computation"], params


async def load(project_id: str) -> dict[str, Computation]:
    from .. import db

    rows = await db.fetch_all("SELECT id, spec FROM computations WHERE project_id=? ORDER BY created_at, id",
                              (project_id,))
    return {r["id"]: Computation.model_validate(db.loads(r["spec"])) for r in rows}


async def run_checked(project_id: str, comp: Computation, values: dict[str, Any]) -> dict[str, Any]:
    """coerce → execute (read-only) → attest -> receipt. Raises ComputeError on bad values or SQL."""
    params = coerce(comp, values)
    result = await asyncio.to_thread(execute, project_id, comp, params)
    checks = attest(comp.attester, result)
    ok = all(c["ok"] for c in checks)
    return {"name": comp.name, "parameters": params, "sql": comp.sql, "result": result, "checks": checks,
            "attested": ok, "answer": render(comp, params, result) if ok else None}
