from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np

from ..core.node import instant_field, register, ui_field
from .base import StoreConfig, VectorStore, l2_score

MIN_INDEX_ROWS = 256  # IVF/PQ training needs at least this many vectors


class LanceConfig(StoreConfig):
    index_type: Literal["none", "IVF_FLAT", "IVF_PQ", "IVF_HNSW_SQ"] = ui_field(
        "none", title="Index type",
        description="none = exact scan. IVF_FLAT clusters vectors; IVF_PQ also compresses them; "
                    "IVF_HNSW_SQ adds a graph per cluster. Indexes need ≥256 vectors.",
    )
    num_partitions: int = ui_field(16, ge=1, le=4096, advanced=True, title="IVF partitions")
    num_sub_vectors: int = ui_field(16, ge=1, le=256, advanced=True, title="PQ sub-vectors",
                                    description="IVF_PQ only. Rounded down to a divisor of the vector size.")
    hnsw_m: int = ui_field(20, ge=4, le=128, advanced=True, title="HNSW links per node (m)")
    ef_construction: int = ui_field(300, ge=8, le=2048, advanced=True, title="HNSW build effort")
    nprobes: int = instant_field(20, ge=1, le=4096, advanced=True, title="Partitions searched (nprobes)")
    refine_factor: int = instant_field(0, ge=0, le=100, advanced=True, title="Refine factor",
                                       description="Re-rank k×factor candidates with exact distances. 0 = off.")
    ef: int = instant_field(64, ge=8, le=4096, advanced=True, title="HNSW search effort (ef)")


@register("vector_store", "lancedb", title="LanceDB",
          description="Embedded, columnar (Arrow) vector database. Exact scan by default; optional IVF/PQ/HNSW indexes.")
class LanceStore(VectorStore):
    Config = LanceConfig
    exact_when = {"index_type": ["none"]}
    TABLE = "chunks"

    def open(self, path: Path, dim: int) -> None:
        import lancedb
        import pyarrow as pa

        self.path, self.dim = path, dim
        path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(path))
        self.notes: list[str] = []
        self.indexed = False
        if self.TABLE in self.db.list_tables().tables:
            self.table = self.db.open_table(self.TABLE)
            self.indexed = bool(self.table.list_indices())
        else:
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("doc_id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), dim)),
            ])
            self.table = self.db.create_table(self.TABLE, schema=schema)

    def _metric(self) -> str:
        return {"cosine": "cosine", "dot": "dot", "l2": "l2"}[self.metric]

    def _maybe_index(self) -> None:
        c: LanceConfig = self.config  # type: ignore[assignment]
        self.notes = []
        if c.index_type == "none":
            return
        n = self.table.count_rows()
        if n < MIN_INDEX_ROWS:
            self.notes.append(f"{c.index_type} skipped: {n} vectors (< {MIN_INDEX_ROWS}); searching exactly")
            self.indexed = False
            return
        from lancedb.index import IvfFlat, IvfHnswSq, IvfPq

        parts = max(1, min(c.num_partitions, n // 2))
        dt = self._metric()
        if c.index_type == "IVF_PQ":
            sub = next(s for s in range(min(c.num_sub_vectors, self.dim), 0, -1) if self.dim % s == 0)
            cfg = IvfPq(distance_type=dt, num_partitions=parts, num_sub_vectors=sub)
        elif c.index_type == "IVF_HNSW_SQ":
            cfg = IvfHnswSq(distance_type=dt, num_partitions=parts, m=c.hnsw_m,
                            ef_construction=c.ef_construction)
        else:
            cfg = IvfFlat(distance_type=dt, num_partitions=parts)
        self.table.create_index("vector", config=cfg, replace=True)
        self.indexed = True

    def upsert(self, ids, doc_ids, vectors):
        with self.lock:
            v = self.prep(vectors)
            if ids:
                self.table.delete("id IN (" + ",".join(f"'{i}'" for i in ids) + ")")
                self.table.add([{"id": i, "doc_id": d, "vector": vec.tolist()}
                                for i, d, vec in zip(ids, doc_ids, v)])
            self._maybe_index()

    def delete_documents(self, doc_ids):
        with self.lock:
            if doc_ids:
                self.table.delete("doc_id IN (" + ",".join(f"'{d}'" for d in doc_ids) + ")")

    def search(self, query, k, params=None):
        p: LanceConfig = params or self.config  # type: ignore[assignment]
        with self.lock:
            if self.table.count_rows() == 0:
                return []
            q = self.prep(np.asarray(query)[None, :])[0]
            qb = self.table.search(q.tolist()).distance_type(self._metric()).limit(k)
            if self.indexed:
                qb = qb.nprobes(p.nprobes)
                if p.refine_factor:
                    qb = qb.refine_factor(p.refine_factor)
                if p.index_type == "IVF_HNSW_SQ":
                    qb = qb.ef(p.ef)
            else:
                qb = qb.bypass_vector_index()
            rows = qb.select(["id"]).to_list()
        hits = []
        for r in rows:
            d = float(r["_distance"])
            score = l2_score(float(np.sqrt(max(d, 0)))) if self.metric == "l2" else 1.0 - d
            hits.append((r["id"], score))
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits

    def count(self):
        return self.table.count_rows()

    def close(self):
        self.table = None
        self.db = None

    def info(self):
        return {"notes": self.notes} if getattr(self, "notes", None) else {}
