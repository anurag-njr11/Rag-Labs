"""One shared aiosqlite connection.

Reads go straight through. Every write goes through `tx()`, which serialises
writers with a lock so two coroutines never interleave statements inside one
transaction on the shared connection.
"""

import asyncio
import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

_conn: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def check_fts5() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            "This Python's SQLite lacks FTS5, which keyword and exact-match search need."
        ) from e
    finally:
        conn.close()


async def connect(path: Path) -> aiosqlite.Connection:
    global _conn
    if _conn is not None:
        return _conn
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _conn = conn
    return conn


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


def conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("database not connected")
    return _conn


@asynccontextmanager
async def tx() -> AsyncIterator[aiosqlite.Connection]:
    async with _write_lock:
        c = conn()
        await c.execute("BEGIN")
        try:
            yield c
        except BaseException:
            await c.execute("ROLLBACK")
            raise
        else:
            await c.execute("COMMIT")


async def fetch_one(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    async with conn().execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    async with conn().execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(s: str | None, default: Any = None) -> Any:
    return json.loads(s) if s else default
