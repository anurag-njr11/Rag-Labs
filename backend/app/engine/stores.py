"""Keeps one open vector-store instance per build.

Stores are opened with the build's configuration (the fields that shaped the
index). Search-time parameters come from whichever pipeline version is asking.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from .. import db
from ..config import get_settings
from ..core.node import get_spec
from ..core.pipeline import default_for
from ..vectorstores.base import VectorStore

_open: dict[str, VectorStore] = {}
_lock = asyncio.Lock()


def store_path(project_id: str, build_id: str) -> Path:
    return get_settings().stores_dir / project_id / build_id


def store_config(build: dict[str, Any]) -> dict[str, Any]:
    cfg = db.loads(build["config"], {})["vector_store"]
    return {**default_for("vector_store", cfg["type"]), **cfg}


async def open_store(build: dict[str, Any]) -> VectorStore:
    if build["id"] in _open:
        return _open[build["id"]]
    async with _lock:
        if build["id"] not in _open:
            cfg = store_config(build)
            params = {k: v for k, v in cfg.items() if k != "type"}
            store = get_spec("vector_store", cfg["type"]).cls(params)
            await asyncio.to_thread(store.open, Path(build["store_path"]), int(build["dim"]))
            _open[build["id"]] = store
        return _open[build["id"]]


async def close_store(build_id: str) -> None:
    store = _open.pop(build_id, None)
    if store is not None:
        await asyncio.to_thread(store.close)


async def close_all() -> None:
    for build_id in list(_open):
        await close_store(build_id)


async def drop_store_files(project_id: str, build_id: str) -> None:
    await close_store(build_id)
    await asyncio.to_thread(shutil.rmtree, store_path(project_id, build_id), True)
