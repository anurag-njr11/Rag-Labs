from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np

from ..core.node import register, ui_field
from .base import StoreConfig, VectorStore, l2_score


class QdrantConfig(StoreConfig):
    on_disk_payload: bool = ui_field(True, advanced=True, title="Store payload on disk")


def _pid(chunk_id: str) -> str:
    # Qdrant point ids must be ints or UUIDs; chunk ids are UUID hex.
    return str(uuid.UUID(hex=chunk_id))


def _cid(point_id: str) -> str:
    return uuid.UUID(str(point_id)).hex


@register("vector_store", "qdrant", title="Qdrant (local mode)",
          description="Qdrant's embedded mode — same API as a Qdrant server. Local mode searches exactly; "
                      "HNSW tuning applies once you point it at a server.",
          exact=True)
class QdrantStore(VectorStore):
    Config = QdrantConfig
    _exact = True
    COLLECTION = "chunks"

    def open(self, path: Path, dim: int) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.path, self.dim = path, dim
        path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(path))
        if not self.client.collection_exists(self.COLLECTION):
            dist = {"cosine": Distance.COSINE, "dot": Distance.DOT, "l2": Distance.EUCLID}[self.metric]
            self.client.create_collection(
                self.COLLECTION,
                vectors_config=VectorParams(size=dim, distance=dist),
                on_disk_payload=self.config.on_disk_payload,
            )

    def upsert(self, ids, doc_ids, vectors):
        from qdrant_client.models import PointStruct

        with self.lock:
            v = self.prep(vectors)
            for i in range(0, len(ids), 256):
                self.client.upsert(
                    self.COLLECTION,
                    points=[
                        PointStruct(id=_pid(cid), vector=vec.tolist(), payload={"doc_id": d})
                        for cid, d, vec in zip(ids[i:i + 256], doc_ids[i:i + 256], v[i:i + 256])
                    ],
                )

    def delete_documents(self, doc_ids):
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchAny

        with self.lock:
            if doc_ids:
                self.client.delete(
                    self.COLLECTION,
                    points_selector=FilterSelector(
                        filter=Filter(must=[FieldCondition(key="doc_id", match=MatchAny(any=list(doc_ids)))])
                    ),
                )

    def search(self, query, k, params=None):
        with self.lock:
            q = self.prep(np.asarray(query)[None, :])[0]
            res = self.client.query_points(self.COLLECTION, query=q.tolist(), limit=k)
        hits = []
        for pt in res.points:
            score = l2_score(pt.score) if self.metric == "l2" else float(pt.score)
            hits.append((_cid(pt.id), score))
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits

    def count(self):
        return self.client.count(self.COLLECTION, exact=True).count

    def close(self):
        if getattr(self, "client", None) is not None:
            self.client.close()
            self.client = None
