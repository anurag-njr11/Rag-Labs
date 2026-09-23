"""Content-addressed hashing and the on-disk artifact cache.

Parsed documents and chunk lists are cached as JSON keyed by the hash of
everything that produced them, so re-running a build with the same inputs
does no work, and a config change only redoes the stages it affects.
Vectors are cached in SQLite (see ingest.embedding).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / key[:2] / f"{key}.json"

    def get(self, kind: str, key: str) -> Any | None:
        p = self._path(kind, key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, kind: str, key: str, value: Any) -> None:
        p = self._path(kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash never leaves a half-written entry.
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
