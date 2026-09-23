"""Rerank slot: re-score retrieved chunks with a cross-encoder, which reads the
question and chunk together — slower than vector search, but sharper."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Literal

from ..config import get_settings
from ..core.node import Node, NodeConfig, register, ui_field

RERANK_MODELS = {
    "Xenova/ms-marco-MiniLM-L-6-v2": "80 MB · fastest",
    "Xenova/ms-marco-MiniLM-L-12-v2": "120 MB",
    "jinaai/jina-reranker-v1-tiny-en": "130 MB",
    "jinaai/jina-reranker-v1-turbo-en": "150 MB",
    "BAAI/bge-reranker-base": "1 GB · most accurate",
}


class NoRerankConfig(NodeConfig):
    pass


@register("rerank", "none", title="Off", description="Keep the retrieval order.")
class NoRerank(Node):
    Config = NoRerankConfig

    async def rerank(self, question: str, items: list[tuple[str, str]]) -> list[tuple[str, float]] | None:
        return None


_models: dict[str, Any] = {}
_lock = threading.Lock()


def _load(name: str) -> Any:
    with _lock:
        if name not in _models:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            cache = get_settings().cache_dir / "models"
            cache.mkdir(parents=True, exist_ok=True)
            _models[name] = TextCrossEncoder(model_name=name, cache_dir=str(cache))
        return _models[name]


class CrossEncoderConfig(NodeConfig):
    model: Literal[tuple(RERANK_MODELS)] = ui_field(  # type: ignore[valid-type]
        "Xenova/ms-marco-MiniLM-L-6-v2", title="Model",
        description="Runs locally. Downloaded once on first use.",
        json_schema_extra={"enum_labels": {k: f"{k} · {v}" for k, v in RERANK_MODELS.items()}},
    )
    top_n: int = ui_field(5, ge=1, le=50, title="Keep top N",
                          description="How many chunks survive reranking and go to the prompt.")


@register("rerank", "cross_encoder", title="Cross-encoder (local)",
          description="Re-scores each (question, chunk) pair. Usually a big precision win for a little latency.")
class CrossEncoderRerank(Node):
    Config = CrossEncoderConfig

    def _score(self, question: str, texts: list[str]) -> list[float]:
        return [float(s) for s in _load(self.config.model).rerank(question, texts)]

    async def rerank(self, question: str, items: list[tuple[str, str]]) -> list[tuple[str, float]]:
        """items: (chunk_id, text). Returns (chunk_id, score) best first, top_n only."""
        if not items:
            return []
        scores = await asyncio.to_thread(self._score, question, [t for _, t in items])
        ranked = sorted(zip((cid for cid, _ in items), scores), key=lambda x: (-x[1], x[0]))
        return ranked[: self.config.top_n]
