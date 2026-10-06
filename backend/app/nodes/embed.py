"""Embed slot: text → vectors.

`embed_key()` identifies everything that affects *document* vectors; the
vector cache is keyed on (chunk text sha, embed_key), so rebuilding with the
same embedder — or switching vector store — never re-embeds.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Awaitable, Callable, Literal

import numpy as np

from ..config import get_settings
from ..core.cache import stable_hash
from ..core.node import Node, NodeConfig, instant_field, register, ui_field
from ..llm import provider as llm

Progress = Callable[[int, int], Awaitable[None] | None]

# `mteb`: MTEB English *Retrieval* average (nDCG@10, 15 BEIR datasets) as self-reported on
# each model card, checked 2026-10-06 — a starting point for sweeps (PRD FR-2.19), not a verdict:
# measure on your own corpus. None = the card reports no comparable retrieval figure
# (nomic v1.5 only publishes the overall MTEB average; bge-m3 reports multilingual benchmarks).
FASTEMBED_MODELS = {
    # Lightweight & balanced
    "BAAI/bge-small-en-v1.5": {"dim": 384, "size": "67 MB", "mteb": 51.68},
    "sentence-transformers/all-MiniLM-L6-v2": {"dim": 384, "size": "90 MB", "mteb": 41.95},
    "snowflake/snowflake-arctic-embed-s": {"dim": 384, "size": "130 MB", "mteb": 51.98},
    # Standard & recommended
    "BAAI/bge-base-en-v1.5": {"dim": 768, "size": "210 MB", "mteb": 53.25},
    "nomic-ai/nomic-embed-text-v1.5": {"dim": 768, "size": "520 MB", "mteb": None},
    # High quality & specialized
    "mixedbread-ai/mxbai-embed-large-v1": {"dim": 1024, "size": "640 MB", "mteb": 54.39},
    # HuggingFace additions
    "BAAI/bge-m3": {"dim": 1024, "size": "1 GB", "mteb": None},  # Multilingual
    "intfloat/e5-large-v2": {"dim": 1024, "size": "1.3 GB", "mteb": 50.56},
    "jinaai/jina-embeddings-v2-base-en": {"dim": 768, "size": "150 MB", "mteb": 47.87},  # Long context (8k)
}


def mteb_label(model: str) -> str:
    score = FASTEMBED_MODELS[model]["mteb"]
    return f"MTEB retrieval {score:.1f}" if score is not None else "MTEB retrieval not reported"

# Instruction prefixes the model authors recommend. Used when the prefix field is left empty.
DEFAULT_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-ai/nomic-embed-text-v1.5": ("search_query: ", "search_document: "),
    "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "BAAI/bge-base-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "BAAI/bge-m3": ("Represent this sentence for searching relevant passages: ", ""),
    "mixedbread-ai/mxbai-embed-large-v1": ("Represent this sentence for searching relevant passages: ", ""),
    "snowflake/snowflake-arctic-embed-s": ("Represent this sentence for searching relevant passages: ", ""),
    "intfloat/e5-large-v2": ("query: ", "passage: "),
    "jinaai/jina-embeddings-v2-base-en": ("", ""),  # No specific prefixes needed
}


def l2_normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


async def _report(progress: Progress | None, done: int, total: int) -> None:
    if progress is not None:
        r = progress(done, total)
        if asyncio.iscoroutine(r):
            await r


class BaseEmbedder(Node):
    def prefixes(self) -> tuple[str, str]:
        return "", ""

    def embed_key(self) -> str:
        c = self.config
        return stable_hash({
            "type": self.type,
            "model": c.model,
            "provider": getattr(c, "provider", None),
            "normalize": c.normalize,
            "doc_prefix": self.prefixes()[1],
        })[:24]

    async def embed_documents(self, texts: list[str], progress: Progress | None = None) -> np.ndarray:
        raise NotImplementedError

    async def embed_query(self, text: str) -> np.ndarray:
        raise NotImplementedError


# --- local (fastembed) ------------------------------------------------------

class ModelLoadError(RuntimeError):
    """A local model couldn't be downloaded or loaded — an environment problem, not a document one."""


_models: dict[tuple[Any, str], Any] = {}
_loading: dict[tuple[Any, str], Future] = {}
_model_lock = threading.Lock()


def load_local_model(factory: Callable[..., Any], name: str) -> Any:
    """`factory(model_name=name, cache_dir=...)`, once per (factory, name); downloads on first use.

    fastembed's Hub metadata calls (`model_info`, `list_repo_tree`) pass `timeout=None`, so a
    stalled connection hangs forever and no HF_HUB_* timeout reaches them. The load therefore runs
    in a daemon thread and callers give up after `model_download_timeout_s`. A timed-out attempt
    is forgotten so the next call starts afresh; Hugging Face downloads into `*.incomplete` blobs
    under a file lock and fastembed's GCS fallback stages in a temp dir, so a partial download
    never leaves a cache entry that looks complete.
    """
    key = (factory, name)
    with _model_lock:
        if key in _models:
            return _models[key]
        fut = _loading.get(key)
        if fut is None:
            fut = _loading[key] = Future()
            threading.Thread(target=_load_into, args=(key, fut), name=f"load {name}", daemon=True).start()
    try:
        return fut.result(timeout=get_settings().model_download_timeout_s)
    except FutureTimeout:
        with _model_lock:
            if _loading.get(key) is fut:
                del _loading[key]
        raise ModelLoadError(f"Downloading {name} timed out — check your connection and retry.") from None
    except Exception as e:
        raise ModelLoadError(f"Could not load {name}: {e}") from e


def _load_into(key: tuple[Any, str], fut: Future) -> None:
    factory, name = key
    try:
        cache = get_settings().cache_dir / "models"
        cache.mkdir(parents=True, exist_ok=True)
        model = factory(model_name=name, cache_dir=str(cache))
    except BaseException as e:
        with _model_lock:
            if _loading.get(key) is fut:
                del _loading[key]
        fut.set_exception(e)
        return
    with _model_lock:
        _models[key] = model
        if _loading.get(key) is fut:
            del _loading[key]
    fut.set_result(model)


def _load_fastembed(name: str) -> Any:
    from fastembed import TextEmbedding

    return load_local_model(TextEmbedding, name)


FastembedModel = Literal[tuple(FASTEMBED_MODELS)]  # type: ignore[valid-type]


class FastembedConfig(NodeConfig):
    model: FastembedModel = ui_field(  # type: ignore[valid-type]
        "BAAI/bge-small-en-v1.5", title="Model",
        description="Runs on your computer. Downloaded once on first use.",
        json_schema_extra={"enum_labels": {k: f"{k} · {v['dim']}d · {v['size']} · {mteb_label(k)}"
                                           for k, v in FASTEMBED_MODELS.items()}},
    )
    normalize: bool = ui_field(True, title="Normalise vectors",
                               description="Scale vectors to unit length (makes cosine = dot product).")
    doc_prefix: str | None = ui_field(None, advanced=True, title="Document prefix",
                                      description="Text prepended to every chunk before embedding. Empty = model default.")
    query_prefix: str | None = instant_field(None, advanced=True, title="Query prefix",
                                             description="Text prepended to questions. Empty = model default.")
    batch_size: int = instant_field(32, ge=1, le=512, advanced=True, title="Batch size")


@register("embed", "fastembed", title="Local model (fastembed)",
          description="Free, private, and deterministic. Runs on CPU.")
class FastembedEmbedder(BaseEmbedder):
    Config = FastembedConfig

    def prefixes(self) -> tuple[str, str]:
        dq, dd = DEFAULT_PREFIXES.get(self.config.model, ("", ""))
        q = self.config.query_prefix if self.config.query_prefix is not None else dq
        d = self.config.doc_prefix if self.config.doc_prefix is not None else dd
        return q, d

    def _embed(self, texts: list[str]) -> np.ndarray:
        model = _load_fastembed(self.config.model)
        vecs = np.array(list(model.embed(texts, batch_size=self.config.batch_size)), dtype=np.float32)
        return l2_normalize(vecs) if self.config.normalize else vecs

    async def embed_documents(self, texts, progress=None):
        _, dp = self.prefixes()
        out: list[np.ndarray] = []
        step = max(self.config.batch_size * 4, 64)
        for i in range(0, len(texts), step):
            batch = [dp + t for t in texts[i:i + step]]
            out.append(await asyncio.to_thread(self._embed, batch))
            await _report(progress, min(i + step, len(texts)), len(texts))
        return np.vstack(out) if out else np.zeros((0, 0), dtype=np.float32)

    async def embed_query(self, text):
        qp, _ = self.prefixes()
        return (await asyncio.to_thread(self._embed, [qp + text]))[0]


# --- API (Gemini / NVIDIA, OpenAI-compatible) ------------------------------


class ApiEmbedConfig(NodeConfig):
    provider: Literal["gemini", "nvidia"] = ui_field("gemini", title="Provider",
                                                     description="Uses your free API quota.")
    model: str = ui_field("", title="Model",
                          description="Empty = the provider's default embedding model.",
                          json_schema_extra={"options_from": "/api/providers/{provider}/models?kind=embed"})
    normalize: bool = ui_field(True, title="Normalise vectors")
    batch_size: int = instant_field(50, ge=1, le=250, advanced=True, title="Batch size")


EMBED_PROVIDERS = ("gemini", "nvidia")


def _api_available() -> tuple[bool, str]:
    if any(llm.availability(p)[0] for p in EMBED_PROVIDERS):
        return True, ""
    return False, "Add GEMINI_API_KEY or NVIDIA_API_KEY to .env to use API embeddings."


@register("embed", "api", title="API model (Gemini / NVIDIA)",
          description="Hosted embedding models. Uses free-tier quota; slower to build.",
          availability=_api_available)
class ApiEmbedder(BaseEmbedder):
    Config = ApiEmbedConfig

    @property
    def model_name(self) -> str:
        c = self.config
        return c.model or llm.get(c.provider).default_embed_model

    def embed_key(self) -> str:
        c = self.config
        return stable_hash({"type": self.type, "provider": c.provider, "model": self.model_name,
                            "normalize": c.normalize})[:24]

    async def _embed(self, texts: list[str], input_type: str) -> np.ndarray:
        c = self.config
        extra = {"input_type": input_type, "truncate": "END"} if c.provider == "nvidia" else None
        try:
            resp = await llm.client(c.provider).embeddings.create(
                model=self.model_name, input=texts, extra_body=extra
            )
        except Exception as e:
            raise llm.friendly_error(c.provider, e) from e
        vecs = np.array([d.embedding for d in sorted(resp.data, key=lambda d: d.index)], dtype=np.float32)
        return l2_normalize(vecs) if c.normalize else vecs

    async def embed_documents(self, texts, progress=None):
        out: list[np.ndarray] = []
        bs = self.config.batch_size
        for i in range(0, len(texts), bs):
            out.append(await self._embed(texts[i:i + bs], "passage"))
            await _report(progress, min(i + bs, len(texts)), len(texts))
        return np.vstack(out) if out else np.zeros((0, 0), dtype=np.float32)

    async def embed_query(self, text):
        return (await self._embed([text], "query"))[0]
