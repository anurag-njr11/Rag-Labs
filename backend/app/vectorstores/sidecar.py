"""Raw vectors + ids kept alongside an index, for stores that must rebuild
their index to delete (FAISS HNSW can't remove points) or that have no
storage of their own (numpy)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np


class Sidecar:
    def __init__(self, root: Path, dim: int) -> None:
        self.root = root
        self.dim = dim
        self.ids: list[str] = []
        self.doc_ids: list[str] = []
        self.vectors = np.zeros((0, dim), dtype=np.float32)

    @property
    def _vec_path(self) -> Path:
        return self.root / "vectors.npy"

    @property
    def _ids_path(self) -> Path:
        return self.root / "ids.json"

    def load(self) -> None:
        if self._ids_path.exists() and self._vec_path.exists():
            data = json.loads(self._ids_path.read_text(encoding="utf-8"))
            self.ids, self.doc_ids = data["ids"], data["doc_ids"]
            self.vectors = np.load(self._vec_path)

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp_v = self.root / "vectors.tmp.npy"
        np.save(tmp_v, self.vectors)
        os.replace(tmp_v, self._vec_path)
        tmp_i = self.root / "ids.tmp.json"
        tmp_i.write_text(json.dumps({"ids": self.ids, "doc_ids": self.doc_ids}), encoding="utf-8")
        os.replace(tmp_i, self._ids_path)

    def upsert(self, ids: list[str], doc_ids: list[str], vectors: np.ndarray) -> None:
        existing = set(ids)
        if existing & set(self.ids):
            keep = [i for i, cid in enumerate(self.ids) if cid not in existing]
            self._keep(keep)
        self.ids.extend(ids)
        self.doc_ids.extend(doc_ids)
        self.vectors = np.vstack([self.vectors, np.asarray(vectors, dtype=np.float32)])

    def delete_documents(self, doc_ids: list[str]) -> int:
        drop = set(doc_ids)
        keep = [i for i, d in enumerate(self.doc_ids) if d not in drop]
        removed = len(self.ids) - len(keep)
        self._keep(keep)
        return removed

    def _keep(self, idx: list[int]) -> None:
        self.ids = [self.ids[i] for i in idx]
        self.doc_ids = [self.doc_ids[i] for i in idx]
        self.vectors = self.vectors[idx] if idx else np.zeros((0, self.dim), dtype=np.float32)
