from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.node import register
from .base import StoreConfig, VectorStore, l2_score
from .sidecar import Sidecar


class NumpyConfig(StoreConfig):
    pass


@register("vector_store", "numpy", title="In-memory (NumPy, exact)",
          description="Brute-force search over every vector. Exact and deterministic — the reference baseline.",
          exact=True)
class NumpyStore(VectorStore):
    Config = NumpyConfig
    _exact = True

    def open(self, path: Path, dim: int) -> None:
        self.path, self.dim = path, dim
        self.side = Sidecar(path, dim)
        self.side.load()

    def upsert(self, ids, doc_ids, vectors):
        with self.lock:
            self.side.upsert(ids, doc_ids, self.prep(vectors))
            self.side.save()

    def delete_documents(self, doc_ids):
        with self.lock:
            if self.side.delete_documents(doc_ids):
                self.side.save()

    def search(self, query, k, params=None):
        with self.lock:
            m = self.side.vectors
            if len(m) == 0:
                return []
            q = self.prep(np.asarray(query)[None, :])[0]
            if self.metric == "l2":
                d = np.linalg.norm(m - q, axis=1)
                scores = np.array([l2_score(x) for x in d])
            else:
                scores = m @ q
            k = min(k, len(scores))
            # Stable tie-break: score desc, then chunk id.
            order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), self.side.ids[i]))[:k]
            return [(self.side.ids[i], float(scores[i])) for i in order]

    def count(self):
        return len(self.side.ids)
