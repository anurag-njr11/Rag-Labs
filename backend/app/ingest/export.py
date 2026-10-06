"""Standalone export: bundle a built version into a plug-and-play zip.

The zip is self-contained — README, requirements.txt, .env.example,
config.json, the build's chunks/vectors, and a `rag.py` runtime ported from
the live engine (`app/ingest/rag_template.py`) that imports nothing from the
`app` package and never requires whichever vector-store library the project
happened to use (retrieval is brute-force NumPy over the exported vectors).
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from .. import db, vault
from ..core.node import build_node
from ..core.pipeline import PipelineConfig, with_defaults
from ..llm import provider as llm

_RAG_TEMPLATE_PATH = Path(__file__).with_name("rag_template.py")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return s or "project"


async def resolved_config(version: dict[str, Any]) -> PipelineConfig:
    """`with_defaults`, plus: an empty "model" (meaning "provider's current
    default") is resolved to a concrete id. The live backend re-resolves this
    on every call (`resolve_model`, with fallback if a model is retired); the
    standalone export can't do that without its own model-listing logic, so it
    bakes in whichever model was actually available at export time instead."""
    cfg = with_defaults(db.loads(version["config"], {}))
    gen = cfg["generate"]
    if not gen.get("model") and gen["type"] in llm.PROVIDERS:
        cfg["generate"] = {**gen, "model": await llm.resolve_model(gen["type"], "chat")}
    emb = cfg["embed"]
    if emb["type"] == "api" and not emb.get("model"):
        cfg["embed"] = {**emb, "model": await llm.resolve_model(emb["provider"], "embed")}
    return cfg


def _requirements(cfg: PipelineConfig) -> str:
    pkgs: dict[str, str] = {"numpy": "numpy>=2.5.3"}
    if cfg["embed"]["type"] == "fastembed" or cfg["rerank"]["type"] == "cross_encoder":
        pkgs["fastembed"] = "fastembed>=0.8.1"
    if cfg["embed"]["type"] == "api" or cfg["generate"]["type"] in llm.PROVIDERS:
        pkgs["openai"] = "openai>=3.19.0"
    return "\n".join(sorted(pkgs.values())) + "\n"


def _used_providers(cfg: PipelineConfig) -> list[str]:
    names: set[str] = set()
    if cfg["embed"]["type"] == "api":
        names.add(cfg["embed"]["provider"])
    if cfg["generate"]["type"] in llm.PROVIDERS:
        names.add(cfg["generate"]["type"])
    return sorted(names)


def _providers_section(cfg: PipelineConfig) -> dict[str, dict[str, Any]]:
    """Connection details rag.py needs for each provider the pipeline calls.
    Keys are never exported, only the env var to read them from; header values
    may be secrets too, so only header names are listed; credentials inside a
    base URL are masked."""
    out = {}
    for name in _used_providers(cfg):
        p = llm.get(name)
        # A URL with embedded credentials (only possible via .env) is exported masked;
        # rag.py then needs the real one in <NAME>_BASE_URL.
        out[name] = {"title": p.title, "base_url": vault.redact_url(p.base_url),
                     "base_url_env": llm.env_prefix(name) + "_BASE_URL",
                     "base_url_has_credentials": vault.url_has_credentials(p.base_url),
                     "api_key_env": p.key_env,
                     "key_required": p.key_required, "default_model": p.default_model,
                     "default_embed_model": p.default_embed_model,
                     "extra_header_names": sorted(p.headers)}
    return out


def _env_example(cfg: PipelineConfig) -> str:
    lines = []
    for name, info in _providers_section(cfg).items():
        lines.append(f"{info['api_key_env']}=" + ("" if info["key_required"] else "  # optional for this endpoint"))
        if info["base_url_has_credentials"]:
            lines.append(f"{info['base_url_env']}=  # required: the full {info['title']} URL (exported masked)")
        if info["extra_header_names"]:
            lines.append(f"# {info['title']} also needs these HTTP headers (set them in rag.py's generate()): "
                         + ", ".join(info["extra_header_names"]))
    return "\n".join(lines) + ("\n" if lines else "")


def _readme(project: dict[str, Any], version: dict[str, Any], cfg: PipelineConfig) -> str:
    local = [m for m in (cfg["embed"]["model"] if cfg["embed"]["type"] == "fastembed" else None,
                         cfg["rerank"]["model"] if cfg["rerank"]["type"] == "cross_encoder" else None) if m]
    first_run = (
        f"\nThe first run downloads {' and '.join(f'`{m}`' for m in local)} into `models/` next to `rag.py`"
        " (set `FASTEMBED_CACHE_PATH` to put them elsewhere); later runs reuse them offline.\n"
        if local else ""
    )
    return f"""# {project['name']} — standalone RAG export

Exported from RAGLabs: project "{project['name']}", version {version['version']}.

Pipeline: parse={cfg['parse']['type']} · chunk={cfg['chunk']['type']} · embed={cfg['embed']['type']} · \
retrieve={cfg['retrieve']['type']} · rerank={cfg['rerank']['type']} · prompt={cfg['prompt']['type']} · \
generate={cfg['generate']['type']}

This bundle runs with **zero** dependency on the RAGLabs backend, the `app` package, or any
vector-store library (FAISS/Chroma/Qdrant/LanceDB) — retrieval is brute-force NumPy cosine/dot/L2
search over the vectors in `data/vectors.npy`, which is fine at this corpus's chunk count.

## Setup

    python -m venv .venv
    .venv\\Scripts\\activate        # Windows
    source .venv/bin/activate      # macOS / Linux
    pip install -r requirements.txt

Copy `.env.example` to `.env` and fill in the API key(s) it lists (only needed if this
pipeline uses an API embedder or generator).

## Run

    python rag.py "your question here"

With no arguments, `rag.py` starts an interactive prompt (empty line or Ctrl+C to quit).
It's also importable: `from rag import answer; answer("...")`.
{first_run}
## Contents

- `rag.py` — the standalone runtime (retrieval, fusion, rerank, prompt, generate).
- `config.json` — the resolved pipeline configuration this was exported from.
- `data/chunks.jsonl` — one JSON object per indexed chunk.
- `data/vectors.npy` — float32 embedding matrix, row-aligned with `chunks.jsonl`.
""" + ("- `models/` — created on first run; downloaded local models.\n" if local else "")


async def build_export_zip(project: dict[str, Any], version: dict[str, Any], build: dict[str, Any]) -> bytes:
    cfg = await resolved_config(version)
    embedder = build_node("embed", cfg["embed"])
    embed_key = embedder.embed_key()

    rows = await db.fetch_all(
        "SELECT c.id, c.text, c.text_sha, c.page_start, c.page_end, c.heading_path, c.is_table,"
        " d.filename AS document, d.source_url"
        " FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE c.build_id = ? ORDER BY d.filename, c.ordinal",
        (build["id"],),
    )

    dim = int(build["dim"] or 0)
    shas = list(dict.fromkeys(r["text_sha"] for r in rows))
    by_sha: dict[str, np.ndarray] = {}
    if shas:
        for i in range(0, len(shas), 500):
            part = shas[i:i + 500]
            vec_rows = await db.fetch_all(
                f"SELECT text_sha, vector FROM vector_cache WHERE embed_key=? AND text_sha IN"
                f" ({','.join('?' * len(part))})",
                (embed_key, *part),
            )
            for r in vec_rows:
                by_sha[r["text_sha"]] = np.frombuffer(r["vector"], dtype=np.float32)

    matrix = np.zeros((len(rows), dim), dtype=np.float32)
    chunk_lines: list[str] = []
    missing = 0
    for i, r in enumerate(rows):
        vec = by_sha.get(r["text_sha"])
        if vec is None:
            missing += 1
            continue
        matrix[i] = vec
        chunk_lines.append(json.dumps({
            "id": r["id"], "document": r["document"], "source_url": r["source_url"],
            "page_start": r["page_start"], "page_end": r["page_end"],
            "heading_path": r["heading_path"], "is_table": bool(r["is_table"]), "text": r["text"],
        }, ensure_ascii=False))
    if missing:
        raise RuntimeError(
            f"{missing} chunk(s) are missing their cached vectors; rebuild the index and try again."
        )

    vectors_buf = io.BytesIO()
    np.save(vectors_buf, matrix)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", _readme(project, version, cfg))
        zf.writestr("requirements.txt", _requirements(cfg))
        zf.writestr(".env.example", _env_example(cfg))
        zf.writestr("config.json", json.dumps({**cfg, "providers": _providers_section(cfg)},
                                              indent=2, ensure_ascii=False))
        zf.writestr("data/chunks.jsonl", "\n".join(chunk_lines) + ("\n" if chunk_lines else ""))
        zf.writestr("data/vectors.npy", vectors_buf.getvalue())
        zf.write(_RAG_TEMPLATE_PATH, "rag.py")
    return buf.getvalue()
