"""The standalone export endpoint: a plug-and-play zip that needs no RAG
Builder backend, no `app` import, and no vector-store library at runtime."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import numpy as np
import pytest
from fastapi import HTTPException

import app.nodes  # noqa: F401
from app import db
from app.api.projects import _insert_version, export_version
from app.config import get_settings
from app.core.node import NodeConfig, register
from app.core.pipeline import recommended_pipeline, validate_pipeline
from app.engine import stores
from app.ingest import builder, export as export_mod
from app.nodes.embed import BaseEmbedder, l2_normalize


class _HashConfig(NodeConfig):
    normalize: bool = True
    model: str = "hash"


@register("embed", "export_test_hash", title="Test hash embedder (export tests)")
class _HashEmbedder(BaseEmbedder):
    """Deterministic bag-of-words hashing; no downloads, no network."""
    Config = _HashConfig

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(64, dtype=np.float32)
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        return v

    async def embed_documents(self, texts, progress=None):
        return l2_normalize(np.vstack([self._vec(t) for t in texts]))

    async def embed_query(self, text):
        return l2_normalize(self._vec(text)[None, :])[0]


EXPECTED_FILES = {
    "README.md", "requirements.txt", ".env.example", "config.json",
    "data/chunks.jsonl", "data/vectors.npy", "rag.py",
}


@pytest.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_settings().ensure_dirs()
    await db.connect(get_settings().db_path)
    from app.ingest.documents import create_document

    async with db.tx() as c:
        await c.execute("INSERT INTO projects (id, name, created_at) VALUES ('p', 'Export Test', ?)",
                        (db.now_iso(),))
    await create_document("p", "guide.md",
                          b"# Guide\n\nRAG Builder exports a standalone bundle.\n\n"
                          b"## int_parsing\n\nRaised for bad integers.\n")
    yield "p"
    await stores.close_all()
    await db.close()
    get_settings.cache_clear()


def _cfg(embed_type: str = "export_test_hash", rerank_type: str = "none", generate_type: str = "gemini") -> dict:
    cfg = json.loads(json.dumps(recommended_pipeline()))
    cfg["embed"] = {"type": embed_type}
    cfg["vector_store"] = {"type": "numpy"}
    cfg["rerank"] = {"type": rerank_type}
    cfg["generate"] = {"type": generate_type}
    return validate_pipeline(cfg)


# --- requirements.txt / .env.example: pure config -> text, no build needed ---

def test_requirements_always_includes_numpy_and_pydantic():
    req = export_mod._requirements(_cfg(embed_type="export_test_hash"))
    assert "numpy" in req and "pydantic" in req


def test_requirements_includes_fastembed_only_for_local_embed_or_rerank():
    with_fastembed = export_mod._requirements(_cfg(embed_type="fastembed"))
    assert "fastembed" in with_fastembed

    api_embed_no_rerank = export_mod._requirements(_cfg(embed_type="api", rerank_type="none"))
    assert "fastembed" not in api_embed_no_rerank

    api_embed_with_rerank = export_mod._requirements(_cfg(embed_type="api", rerank_type="cross_encoder"))
    assert "fastembed" in api_embed_with_rerank


def test_requirements_includes_openai_for_api_provider_generate():
    req = export_mod._requirements(_cfg(embed_type="export_test_hash", generate_type="gemini"))
    assert "openai" in req


def test_env_example_lists_only_needed_provider_keys():
    gemini_gen = export_mod._env_example(_cfg(embed_type="export_test_hash", generate_type="gemini"))
    assert "GEMINI_API_KEY" in gemini_gen and "NVIDIA_API_KEY" not in gemini_gen


# --- full endpoint: build a real index, export it, inspect the zip ----------

async def test_export_endpoint_returns_zip_with_expected_files(project):
    cfg = _cfg()
    build = await builder.sync_build(project, cfg)
    assert build["status"] == "ready"
    v = await _insert_version(project, cfg, "export test", None, activate=True)

    resp = await export_version(project, v["id"])
    assert resp.media_type == "application/zip"
    assert "Export-Test" in resp.headers["content-disposition"] or "export-test" in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].startswith("attachment;")

    zf = zipfile.ZipFile(io.BytesIO(resp.body))
    assert set(zf.namelist()) == EXPECTED_FILES

    cfg_out = json.loads(zf.read("config.json"))
    assert cfg_out["embed"]["type"] == "export_test_hash"

    chunk_lines = zf.read("data/chunks.jsonl").decode("utf-8").strip().splitlines()
    assert len(chunk_lines) == build["chunk_count"] > 0
    first = json.loads(chunk_lines[0])
    assert set(first) == {"id", "document", "source_url", "page_start", "page_end",
                          "heading_path", "is_table", "text"}

    vectors = np.load(io.BytesIO(zf.read("data/vectors.npy")))
    assert vectors.shape == (len(chunk_lines), build["dim"])
    assert vectors.dtype == np.float32

    # rag.py must not import anything from the `app` package.
    import ast

    rag_py = zf.read("rag.py").decode("utf-8")
    tree = ast.parse(rag_py, filename="rag.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name == "app" or a.name.startswith("app.") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or not (node.module == "app" or node.module.startswith("app."))


async def test_export_404_unknown_version(project):
    with pytest.raises(HTTPException) as exc:
        await export_version(project, "does-not-exist")
    assert exc.value.status_code == 404


async def test_export_409_when_build_not_synced(project):
    # A version whose config has never been built has no ready+synced index.
    cfg = _cfg(rerank_type="cross_encoder")
    v = await _insert_version(project, cfg, "unbuilt", None, activate=True)
    with pytest.raises(HTTPException) as exc:
        await export_version(project, v["id"])
    assert exc.value.status_code == 409
