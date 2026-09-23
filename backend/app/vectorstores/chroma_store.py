from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.node import instant_field, register, ui_field
from .base import StoreConfig, VectorStore, l2_score

_SPACE = {"cosine": "cosine", "dot": "ip", "l2": "l2"}


class ChromaConfig(StoreConfig):
    hnsw_m: int = ui_field(16, ge=4, le=128, advanced=True, title="HNSW links per node (M)")
    ef_construction: int = ui_field(100, ge=8, le=2048, advanced=True, title="HNSW build effort (ef_construction)")
    ef_search: int = instant_field(100, ge=8, le=4096, advanced=True, title="HNSW search effort (ef_search)",
                                   description="Higher = more accurate, slower.")


@register("vector_store", "chroma", title="Chroma",
          description="Popular open-source vector database, running embedded. Uses an HNSW index (approximate).",
          exact=False)
class ChromaStore(VectorStore):
    Config = ChromaConfig
    _exact = False
    COLLECTION = "chunks"

    def open(self, path: Path, dim: int) -> None:
        import chromadb
        from chromadb.config import Settings

        self.path, self.dim = path, dim
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(path), settings=Settings(anonymized_telemetry=False, allow_reset=True)
        )
        c: ChromaConfig = self.config  # type: ignore[assignment]
        self.col = self.client.get_or_create_collection(
            self.COLLECTION,
            embedding_function=None,
            configuration={"hnsw": {
                "space": _SPACE[self.metric],
                "max_neighbors": c.hnsw_m,
                "ef_construction": c.ef_construction,
                "ef_search": c.ef_search,
            }},
        )
        self._ef = c.ef_search

    def upsert(self, ids, doc_ids, vectors):
        with self.lock:
            v = self.prep(vectors)
            batch = max(1, self.client.get_max_batch_size())
            for i in range(0, len(ids), batch):
                self.col.upsert(
                    ids=ids[i:i + batch],
                    embeddings=v[i:i + batch],
                    metadatas=[{"doc_id": d} for d in doc_ids[i:i + batch]],
                )

    def delete_documents(self, doc_ids):
        with self.lock:
            if doc_ids:
                self.col.delete(where={"doc_id": {"$in": list(doc_ids)}})

    def search(self, query, k, params=None):
        p: ChromaConfig = params or self.config  # type: ignore[assignment]
        with self.lock:
            n = self.col.count()
            if n == 0:
                return []
            if p.ef_search != self._ef:
                self.col.modify(configuration={"hnsw": {"ef_search": p.ef_search}})
                self._ef = p.ef_search
            q = self.prep(np.asarray(query)[None, :])
            res = self.col.query(query_embeddings=q, n_results=min(k, n), include=["distances"])
        hits = []
        for cid, d in zip(res["ids"][0], res["distances"][0]):
            if self.metric == "l2":
                score = l2_score(float(np.sqrt(max(d, 0))))  # Chroma reports squared L2
            else:
                score = 1.0 - float(d)  # cosine and ip distances are 1 - similarity
            hits.append((cid, score))
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits

    def count(self):
        return self.col.count()

    def close(self):
        # Chroma has no public close(); drop references so file handles release.
        self.col = None
        self.client = None
