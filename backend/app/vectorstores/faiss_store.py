from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np

from ..core.node import instant_field, register, ui_field
from .base import StoreConfig, VectorStore, l2_score
from .sidecar import Sidecar


class FaissConfig(StoreConfig):
    index_type: Literal["Flat", "IVFFlat", "HNSW"] = ui_field(
        "Flat", title="Index type",
        description="Flat = exact search. IVFFlat = clusters vectors, searches the nearest clusters. "
                    "HNSW = graph search; fast and approximate.",
    )
    nlist: int = ui_field(64, ge=1, le=65536, advanced=True, title="IVF clusters (nlist)",
                          description="IVF only. Capped to what the corpus size supports.")
    nprobe: int = instant_field(8, ge=1, le=65536, advanced=True, title="IVF clusters searched (nprobe)",
                                description="IVF only. Higher = more accurate, slower.")
    hnsw_m: int = ui_field(32, ge=4, le=128, advanced=True, title="HNSW links per node (M)")
    ef_construction: int = ui_field(200, ge=8, le=2048, advanced=True, title="HNSW build effort (efConstruction)")
    ef_search: int = instant_field(64, ge=8, le=4096, advanced=True, title="HNSW search effort (efSearch)",
                                   description="HNSW only. Higher = more accurate, slower.")


@register("vector_store", "faiss", title="FAISS",
          description="Meta's similarity-search library. Flat is exact; IVF and HNSW trade accuracy for speed.")
class FaissStore(VectorStore):
    Config = FaissConfig
    exact_when = {"index_type": ["Flat"]}

    def open(self, path: Path, dim: int) -> None:
        self.path, self.dim = path, dim
        self.side = Sidecar(path, dim)
        self.side.load()
        self.index = None
        self.notes: list[str] = []
        idx_path = path / "index.faiss"
        if idx_path.exists():
            import faiss

            self.index = faiss.read_index(str(idx_path))
        elif len(self.side.ids):
            self._rebuild()

    def _faiss_metric(self):
        import faiss

        return faiss.METRIC_L2 if self.metric == "l2" else faiss.METRIC_INNER_PRODUCT

    def _rebuild(self) -> None:
        import faiss

        c: FaissConfig = self.config  # type: ignore[assignment]
        n, d = len(self.side.ids), self.dim
        metric = self._faiss_metric()
        self.notes = []
        if c.index_type == "HNSW":
            index = faiss.IndexHNSWFlat(d, c.hnsw_m, metric)
            index.hnsw.efConstruction = c.ef_construction
        elif c.index_type == "IVFFlat" and n > 0:
            nlist = max(1, min(c.nlist, n // 39 or 1))
            if nlist != c.nlist:
                self.notes.append(f"nlist reduced to {nlist} for {n} vectors")
            quant = faiss.IndexFlatL2(d) if metric == faiss.METRIC_L2 else faiss.IndexFlatIP(d)
            index = faiss.IndexIVFFlat(quant, d, nlist, metric)
            index.train(self.side.vectors)
        else:
            index = faiss.IndexFlatL2(d) if metric == faiss.METRIC_L2 else faiss.IndexFlatIP(d)
        if n:
            index.add(self.side.vectors)
        self.index = index
        self.path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.path / "index.faiss"))

    def upsert(self, ids, doc_ids, vectors):
        with self.lock:
            self.side.upsert(ids, doc_ids, self.prep(vectors))
            self.side.save()
            self._rebuild()

    def delete_documents(self, doc_ids):
        with self.lock:
            if self.side.delete_documents(doc_ids):
                self.side.save()
                self._rebuild()

    def search(self, query, k, params=None):
        import faiss

        p: FaissConfig = params or self.config  # type: ignore[assignment]
        with self.lock:
            if self.index is None or self.index.ntotal == 0:
                return []
            if isinstance(self.index, faiss.IndexIVF):
                self.index.nprobe = min(p.nprobe, self.index.nlist)
            if isinstance(self.index, faiss.IndexHNSW):
                self.index.hnsw.efSearch = max(p.ef_search, k)
            q = self.prep(np.asarray(query)[None, :])
            dist, idx = self.index.search(q, min(k, self.index.ntotal))
        hits = []
        for d, i in zip(dist[0], idx[0]):
            if i < 0:
                continue
            score = l2_score(float(np.sqrt(max(d, 0)))) if self.metric == "l2" else float(d)
            hits.append((self.side.ids[i], score))
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits

    def count(self):
        return len(self.side.ids)

    def info(self):
        return {"notes": self.notes} if getattr(self, "notes", None) else {}
