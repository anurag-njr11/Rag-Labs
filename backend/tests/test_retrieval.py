import hashlib
import json

import numpy as np
import pytest

import app.nodes  # noqa: F401
from app import db
from app.config import get_settings
from app.core.node import NodeConfig, RunContext, register
from app.core.pipeline import recommended_pipeline, validate_pipeline
from app.engine import retrieval, stores
from app.engine.chat import extract_citations
from app.ingest import builder, lookup
from app.nodes import chunk as C
from app.nodes import retrieve as R
from app.nodes.embed import BaseEmbedder, l2_normalize


# --- exact-match normalisation ------------------------------------------------

def test_normaliser_collapses_variants():
    a = "AttributeError: 'NoneType' object has no attribute 'get'"
    b = "AttributeError: 'NoneType' object has no attribute 'items'"
    assert lookup.normalize(a) == lookup.normalize(b)
    c = r'File "C:\proj\app\main.py", line 42, in handler at 0x7f3a2b1c'
    d = 'File "/srv/app/main.py", line 7, in handler at 0x55d1'
    assert lookup.normalize(c) == lookup.normalize(d)


def test_query_keys_find_symbols_and_codes():
    keys = dict(lookup.query_keys("Why does Model.model_validate raise [type=int_parsing]?"))
    found = {k for _, k in lookup.query_keys("Why does Model.model_validate raise [type=int_parsing]?")}
    assert "model.model_validate" in found and "int_parsing" in found
    assert keys  # non-empty


# --- ranking math -------------------------------------------------------------

def test_rrf_math_and_tiebreak():
    lists = {"dense": [("a", 0.9), ("b", 0.8)], "keyword": [("b", 5.0), ("c", 1.0)]}
    out = R.rrf(lists, {"dense": 1, "keyword": 1}, 60)
    scores = dict(out)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert out[0][0] == "b"
    # Equal scores break ties by chunk id, deterministically.
    tie = R.rrf({"x": [("z", 1)], "y": [("a", 1)]}, {}, 60)
    assert [cid for cid, _ in tie] == ["a", "z"]


def test_weighted_fusion_normalises():
    out = R.weighted({"dense": [("a", 0.9), ("b", 0.1)], "keyword": [("b", 10.0), ("a", 0.0)]},
                     {"dense": 1.0, "keyword": 2.0})
    assert out[0][0] == "b"


def test_mmr_prefers_diverse_results():
    q = np.array([1.0, 0.0])
    vecs = {"a": np.array([1.0, 0.0]), "a2": np.array([0.99, 0.01]), "b": np.array([0.7, 0.7])}
    ranked = [("a", 3), ("a2", 2), ("b", 1)]
    # Relevance-only keeps the near-duplicate; diversity-leaning swaps it out.
    assert [c for c, _ in R.mmr(ranked, vecs, q, 2, lam=1.0)] == ["a", "a2"]
    assert [c for c, _ in R.mmr(ranked, vecs, q, 2, lam=0.3)] == ["a", "b"]


# --- chunking -----------------------------------------------------------------

PAGES = [{"page": 1, "text": "# Guide\n\n" + ("Intro sentence here. " * 30) +
          "\n\n|a|b|\n|---|---|\n" + "".join(f"|{i}|{i * i}|\n" for i in range(40))}]


@pytest.mark.parametrize("cls", [C.FixedChunker, C.RecursiveChunker, C.SentenceChunker, C.StructureChunker])
def test_tables_are_atomic(cls):
    chunks = cls({"size": 120, "overlap": 20}).chunk(PAGES)
    tables = [c for c in chunks if c["is_table"]]
    rows = [ln for ln in tables[0]["text"].splitlines() if ln.startswith("|")]
    assert len(tables) == 1 and len(rows) == 42  # header + separator + 40 rows
    assert all("|---|" not in c["text"] for c in chunks if not c["is_table"])
    assert all(c["page_start"] == 1 for c in chunks)


def test_chunks_respect_size():
    chunks = C.RecursiveChunker({"size": 200, "overlap": 0}).chunk(PAGES)
    assert all(len(c["text"]) <= 200 for c in chunks if not c["is_table"])


# --- citations ----------------------------------------------------------------

def test_extract_citations():
    included = [
        {"id": "c1", "document_id": "d", "document": "a.md", "page_start": None, "page_end": None,
         "heading_path": "", "text": "Fields without a default are required. Other text."},
        {"id": "c2", "document_id": "d", "document": "b.md", "page_start": 2, "page_end": 2,
         "heading_path": "X", "text": "Use None as a default to make it optional."},
    ]
    answer = "A field without a default is required [1]. Give it None to make it optional [2][9]."
    cites = extract_citations(answer, included)
    assert [c["n"] for c in cites] == [1, 2]
    s, e = cites[0]["spans"][0]
    assert included[0]["text"][s:e].startswith("Fields without a default")


# --- end-to-end retrieval on a real build -------------------------------------


class HashConfig(NodeConfig):
    normalize: bool = True
    model: str = "hash"


@register("embed", "test_hash", title="Test hash embedder")
class HashEmbedder(BaseEmbedder):
    """Deterministic bag-of-words hashing; no downloads."""
    Config = HashConfig

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(64, dtype=np.float32)
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        return v

    async def embed_documents(self, texts, progress=None):
        return l2_normalize(np.vstack([self._vec(t) for t in texts]))

    async def embed_query(self, text):
        return l2_normalize(self._vec(text)[None, :])[0]


DOCS = {
    "errors.md": "# Errors\n\n## int_parsing\n\nRaised for bad integers.\n\n"
                 "    Input should be a valid integer, unable to parse string as an integer "
                 "[type=int_parsing, input_value='x', input_type=str]\n",
    "fields.md": "# Fields\n\n## Optional\n\nGive a field a default value to make it optional.\n",
    "models.md": "# Models\n\nSubclass BaseModel. Validate with Model.model_validate(data).\n",
}


@pytest.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_settings().ensure_dirs()
    await db.connect(get_settings().db_path)
    from app.ingest.documents import create_document

    async with db.tx() as c:
        await c.execute("INSERT INTO projects (id, name, created_at) VALUES ('p', 'P', ?)", (db.now_iso(),))
    for name, text in DOCS.items():
        await create_document("p", name, text.encode())
    yield "p"
    await stores.close_all()
    await db.close()
    get_settings.cache_clear()


def _cfg(store: str) -> dict:
    cfg = json.loads(json.dumps(recommended_pipeline()))
    cfg["embed"] = {"type": "test_hash"}
    cfg["vector_store"] = {"type": store}
    return validate_pipeline(cfg)


@pytest.mark.parametrize("store", ["numpy", "faiss", "lancedb", "qdrant"])
async def test_retrieval_is_deterministic_and_exact_wins(project, store):
    cfg = _cfg(store)
    build = await builder.sync_build(project, cfg)
    assert build["status"] == "ready" and build["chunk_count"] > 0

    q = "Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_type=str]"
    r1 = await retrieval.retrieve(RunContext(), build=build, cfg=cfg, question=q)
    r2 = await retrieval.retrieve(RunContext(), build=build, cfg=cfg, question=q)
    assert [(r["id"], r["score"]) for r in r1] == [(r["id"], r["score"]) for r in r2]
    assert r1[0]["document"] == "errors.md" and "exact" in r1[0]["found_by"]


async def test_resync_uses_caches(project):
    cfg = _cfg("numpy")
    await builder.sync_build(project, cfg)
    other = _cfg("faiss")
    b = await builder.sync_build(project, other)
    stats = db.loads(b["stats"])
    assert stats["vectors_embedded"] == 0 and stats["parse_cache_hits"] == 3
    est = await builder.estimate(project, _cfg("chroma"))
    assert est["kind"] == "reinsert"


async def test_defining_section_beats_incidental_mentions(tmp_path, monkeypatch):
    """Real-corpus regression: the error message is printed in many example
    chunks, while the reference section for it is only *named* by its heading."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_settings().ensure_dirs()
    await db.connect(get_settings().db_path)
    from app.ingest.documents import create_document

    msg = ("#> Input should be a valid integer, unable to parse string as an integer "
           "[type=int_parsing, input_value='x', input_type=str]")
    examples = "\n\n".join(
        f"## Example {i}\n\nSome model walkthrough number {i}.\n\n```\n{msg}\n```" for i in range(6))
    reference = ("# Validation errors\n\n## `int_parsing`\n\n"
                 "This error is raised when the value can't be parsed as `int`.\n")
    try:
        async with db.tx() as c:
            await c.execute("INSERT INTO projects (id, name, created_at) VALUES ('p', 'P', ?)", (db.now_iso(),))
        await create_document("p", "models.md", ("# Models\n\n" + examples).encode())
        await create_document("p", "validation_errors.md", reference.encode())
        cfg = _cfg("numpy")
        build = await builder.sync_build("p", cfg)
        q = "Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_type=str]"
        ranked, keys = await retrieval.exact_search(build["id"], q, 10)
        top = (await retrieval.load_chunks([ranked[0][0]]))[ranked[0][0]]
        assert top["document"] == "validation_errors.md", top["heading_path"]
        assert "heading:int_parsing" in keys[ranked[0][0]]
    finally:
        await stores.close_all()
        await db.close()
        get_settings.cache_clear()


async def test_pinned_definition_ranks_first_after_fusion(project):
    """RRF only sees ranks; a heading-exact match must still come first."""
    cfg = _cfg("numpy")
    build = await builder.sync_build(project, cfg)
    q = "What is int_parsing?"
    res = await retrieval.retrieve(RunContext(), build=build, cfg=cfg, question=q)
    assert res[0]["pinned"] and res[0]["document"] == "errors.md"
    off = validate_pipeline({**cfg, "retrieve": {**cfg["retrieve"], "pin_definitions": False}})
    res_off = await retrieval.retrieve(RunContext(), build=build, cfg=off, question=q)
    assert not any(r["pinned"] for r in res_off)
