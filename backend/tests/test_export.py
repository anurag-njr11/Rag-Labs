"""The standalone export endpoint: a plug-and-play zip that needs no RAG
Builder backend, no `app` import, and no vector-store library at runtime."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import zipfile

import numpy as np
import pytest
from fastapi import HTTPException

import app.nodes  # noqa: F401
from app import db
from app.api.projects import _insert_version, export_version
from app.config import get_settings
from app.core.node import NodeConfig, RunContext, register
from app.core.pipeline import recommended_pipeline, validate_pipeline
from app.engine import retrieval, stores
from app.ingest import builder, export as export_mod
from app.nodes.embed import BaseEmbedder, l2_normalize
from app.nodes.generate import ProviderGenerator


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
    "app/__init__.py", "app/main.py", "Dockerfile", "docker-compose.yml", ".dockerignore",
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
                          b"# Guide\n\nRAGLabs exports a standalone bundle.\n\n"
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

def test_requirements_includes_numpy_but_not_unused_pydantic():
    req = export_mod._requirements(_cfg(embed_type="export_test_hash"))
    assert "numpy" in req and "pydantic" not in req


def test_requirements_include_the_http_server():
    req = export_mod._requirements(_cfg())
    assert "fastapi" in req and "uvicorn" in req


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


def test_readme_mentions_first_run_download_only_for_local_models():
    project, version = {"name": "Demo"}, {"version": 1}
    local = export_mod._readme(project, version, _cfg(embed_type="fastembed", rerank_type="cross_encoder"))
    assert "first run downloads" in local and "`models/`" in local
    remote = export_mod._readme(project, version, _cfg(embed_type="api", rerank_type="none"))
    assert "first run downloads" not in remote and "`models/`" not in remote


# --- rag.py runtime, loaded straight from the template file ------------------

def _load_rag(monkeypatch):
    import importlib.util

    # Importing rag.py setdefaults this env var; pre-set it so monkeypatch restores it afterwards.
    monkeypatch.setenv("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    spec = importlib.util.spec_from_file_location("exported_rag", export_mod._RAG_TEMPLATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rag_cli_reports_errors_without_traceback(monkeypatch, capsys):
    rag = _load_rag(monkeypatch)

    def boom(_q):
        raise RuntimeError("Missing NVIDIA_API_KEY.")

    monkeypatch.setattr(rag, "answer", boom)
    monkeypatch.setattr("sys.argv", ["rag.py", "a question"])
    with pytest.raises(SystemExit) as exc:
        rag.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.strip() == "Error: Missing NVIDIA_API_KEY." and "Traceback" not in err


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
    assert set(first) == {"id", "document_id", "ordinal", "document", "source_url", "page_start", "page_end",
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


# --- the export unzipped and run: HTTP server, and parity with the live engine ---------------

OPS_MD = (b"# Operations\n\n## Backups\n\nNightly backups run at two in the morning and are kept for thirty days.\n\n"
          b"## Restores\n\nRestores are requested through the support portal and take about an hour; "
          b"`backup.restore_now` starts one by hand.\n\n"
          b"## Monitoring\n\nAlerts page the on-call engineer when disk usage passes ninety percent.\n\n"
          b"## Retention\n\nAudit logs are retained for seven years in cold storage.\n")


def _hash_query(text: str, as_passage: bool = False) -> np.ndarray:
    return l2_normalize(_HashEmbedder()._vec(text)[None, :])[0]


@pytest.fixture
async def unzipped(project, tmp_path, monkeypatch):
    """Factory: build + export a config, unzip it, import its rag.py as `rag` (the name app/main.py
    imports). rag.py doesn't know the test hash embedder, so its query side is patched in."""
    from app.ingest.documents import create_document

    await create_document(project, "ops.md", OPS_MD)

    async def make(**retrieve):
        cfg = _cfg()
        cfg = validate_pipeline({**cfg, "retrieve": {**cfg["retrieve"], **retrieve}})
        build = await builder.sync_build(project, cfg)
        v = await _insert_version(project, cfg, "unzipped", None, activate=True)
        out = tmp_path / "export"
        zipfile.ZipFile(io.BytesIO((await export_version(project, v["id"])).body)).extractall(out)
        monkeypatch.syspath_prepend(str(out))
        monkeypatch.setenv("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        sys.modules.pop("rag", None)
        import rag

        monkeypatch.setattr(rag, "embed_query", _hash_query)
        return rag, out, build, cfg

    yield make
    sys.modules.pop("rag", None)


async def _live(build, cfg, question):
    return await retrieval.retrieve(RunContext(), build=build, cfg=cfg, question=question)


def _assert_same_ranking(exported, live):
    assert [r["id"] for r in exported] == [r["id"] for r in live]
    assert [r["score"] for r in exported] == pytest.approx([r["score"] for r in live], abs=1e-5)


async def test_exported_http_server_health_and_chat(unzipped, monkeypatch):
    from fastapi.testclient import TestClient

    rag, out, _, _ = await unzipped()
    spec = importlib.util.spec_from_file_location("exported_server", out / "app" / "main.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    assert server.rag is rag
    prompts = []
    monkeypatch.setattr(rag, "generate",
                        lambda messages: prompts.append(messages) or "Backups are kept for thirty days [1].")

    client = TestClient(server.app)
    assert client.get("/health").json() == {"status": "ok"}
    r = client.post("/chat", json={"question": "How long are nightly backups kept?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Backups are kept for thirty days [1]."
    first = body["sources"][0]
    assert first["n"] == 1 and first["cited"] is True and first["spans"]
    assert {"chunk_id", "document", "source_url", "page_start", "page_end", "heading_path"} <= set(first)
    assert not any(s["cited"] for s in body["sources"][1:])
    assert "thirty days" in prompts[0][1]["content"]

    def boom(_messages):
        raise RuntimeError("Missing GEMINI_API_KEY.")

    monkeypatch.setattr(rag, "generate", boom)
    r = client.post("/chat", json={"question": "anything"})
    assert r.status_code == 502 and r.json()["detail"] == "Missing GEMINI_API_KEY."
    assert client.post("/chat", json={"question": ""}).status_code == 422


@pytest.mark.parametrize("mode", ["multi_query", "hyde"])
async def test_exported_query_expansion_matches_live(unzipped, monkeypatch, mode):
    reply = ("- How long do we keep nightly backups?\n2. backup retention period\n" if mode == "multi_query"
             else "Nightly backups are kept for thirty days, then deleted.")

    async def live_complete(self, prompt, max_tokens):
        return reply, 10, 10

    monkeypatch.setattr(ProviderGenerator, "complete", live_complete)
    monkeypatch.setattr(retrieval, "_expansions", {})
    rag, _, build, cfg = await unzipped(query_expansion=mode)
    prompts, embedded = [], []
    monkeypatch.setattr(rag, "complete", lambda prompt, max_tokens: prompts.append(prompt) or reply)
    monkeypatch.setattr(rag, "embed_query", lambda t, as_passage=False: embedded.append((t, as_passage))
                        or _hash_query(t))

    q = "retention of backups"
    expanded = rag.retrieve(q)
    assert len(prompts) == 1 and q in prompts[0]
    _assert_same_ranking(expanded, await _live(build, cfg, q))
    if mode == "hyde":  # the passage, embedded as a document, replaces the question on the dense path
        assert embedded == [(reply, True)]
    else:  # the question plus each rewrite
        assert [t for t, _ in embedded] == [q, "How long do we keep nightly backups?", "backup retention period"]

    def boom(prompt, max_tokens):
        raise RuntimeError("provider down")

    monkeypatch.setattr(rag, "complete", boom)  # fails soft to the plain question
    plain = validate_pipeline({**cfg, "retrieve": {**cfg["retrieve"], "query_expansion": "none"}})
    soft = rag.retrieve(q)
    _assert_same_ranking(soft, await _live(build, plain, q))
    if mode == "multi_query":
        assert [r["score"] for r in soft] != [r["score"] for r in expanded]


async def test_exported_context_window_matches_live(unzipped):
    rag, _, build, cfg = await unzipped(context_window=1, top_k=2)
    q = "How are restores requested through the support portal?"
    exported, live = rag.retrieve(q), await _live(build, cfg, q)
    _assert_same_ranking(exported, live)
    assert [(r["window"], r["window_text"]) for r in exported] == [(r["window"], r["window_text"]) for r in live]
    assert any(len(r["window"]) == 3 for r in exported)
    # Ranking keeps the hit's own text; only the prompt carries the neighbours.
    top = next(r for r in exported if len(r["window"]) == 3)
    assert top["text"] != top["window_text"] and top["text"] in top["window_text"]
    assert top["window_text"] in rag.build_prompt(q, exported)["messages"][1]["content"]


async def test_exported_exact_path_matches_live(unzipped):
    # Chunk-side symbol mentions aren't exact hits live (keyword search ranks them), nor in the export.
    rag, _, build, cfg = await unzipped()
    q = "What does backup.restore_now do?"
    _assert_same_ranking(rag.retrieve(q), await _live(build, cfg, q))
