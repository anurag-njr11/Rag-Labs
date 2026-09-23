"""Vector store contract.

Every store answers the same questions the same way, so hybrid/fused
retrieval, keyword search and exact lookup (which live in SQLite) behave
identically whichever store is chosen. Scores are always "higher is better":

    cosine → cosine similarity      dot → inner product      l2 → 1 / (1 + distance)

Store methods are synchronous; callers run them in a thread.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np

from ..core.node import Node, NodeConfig, ui_field

Metric = Literal["cosine", "dot", "l2"]
Hit = tuple[str, float]  # (chunk_id, score)


def metric_field() -> Any:
    return ui_field(
        "cosine", title="Distance metric",
        description="Cosine suits almost every text model. Dot product assumes normalised vectors; L2 is Euclidean distance.",
    )


class StoreConfig(NodeConfig):
    metric: Metric = metric_field()


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return (v / n).astype(np.float32)


def l2_score(distance: float) -> float:
    return 1.0 / (1.0 + max(0.0, float(distance)))


class VectorStore(Node):
    Config: ClassVar[type[NodeConfig]] = StoreConfig
    # For the UI: which config makes this store exact, e.g. {"index_type": ["Flat"]}.
    exact_when: ClassVar[dict[str, list[Any]] | None] = None

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self.path: Path | None = None
        self.dim: int | None = None
        self.lock = threading.RLock()

    @property
    def metric(self) -> str:
        return self.config.metric

    def prep(self, vectors: np.ndarray) -> np.ndarray:
        v = np.asarray(vectors, dtype=np.float32)
        return normalize(v) if self.metric == "cosine" else v

    def is_exact(self) -> bool:
        spec_exact = type(self).exact_when
        if spec_exact is None:
            return bool(getattr(type(self), "_exact", False))
        return all(getattr(self.config, k) in vals for k, vals in spec_exact.items())

    # --- to implement ---
    def open(self, path: Path, dim: int) -> None:
        raise NotImplementedError

    def upsert(self, ids: list[str], doc_ids: list[str], vectors: np.ndarray) -> None:
        raise NotImplementedError

    def delete_documents(self, doc_ids: list[str]) -> None:
        raise NotImplementedError

    def search(self, query: np.ndarray, k: int, params: NodeConfig | None = None) -> list[Hit]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def info(self) -> dict[str, Any]:
        """Extra facts for the inspector (e.g. an index that was skipped)."""
        return {}
