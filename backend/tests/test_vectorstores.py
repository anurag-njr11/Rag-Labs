"""Contract tests run against every vector store and index configuration."""

import numpy as np
import pytest

import app.vectorstores  # noqa: F401  (registers stores)
from app.core.node import get_spec

DIM = 32
N = 300  # enough for LanceDB to actually build its IVF indexes

CONFIGS = [
    ("numpy", {}),
    ("faiss", {"index_type": "Flat"}),
    ("faiss", {"index_type": "IVFFlat", "nlist": 4, "nprobe": 4}),
    ("faiss", {"index_type": "HNSW"}),
    ("chroma", {}),
    ("qdrant", {}),
    ("lancedb", {"index_type": "none"}),
    ("lancedb", {"index_type": "IVF_FLAT", "num_partitions": 4, "nprobes": 4}),
]
EXACT = [c for c in CONFIGS if c[0] in ("numpy", "qdrant")
         or c == ("faiss", {"index_type": "Flat"}) or c == ("lancedb", {"index_type": "none"})]


def make(store_type, cfg, metric="cosine"):
    return get_spec("vector_store", store_type).cls({**cfg, "metric": metric})


@pytest.fixture(scope="module")
def data():
    rng = np.random.default_rng(42)
    vecs = rng.normal(size=(N, DIM)).astype(np.float32)
    ids = [f"{i:032x}" for i in range(N)]
    docs = [f"doc{i % 5}" for i in range(N)]
    return ids, docs, vecs


@pytest.mark.parametrize("store_type,cfg", CONFIGS, ids=lambda c: str(c))
def test_contract(tmp_path, data, store_type, cfg):
    ids, docs, vecs = data
    s = make(store_type, cfg)
    s.open(tmp_path / "s", DIM)
    s.upsert(ids, docs, vecs)
    assert s.count() == N

    # A vector finds itself first.
    for i in (0, 57, 199):
        hits = s.search(vecs[i], 5)
        assert hits[0][0] == ids[i], (store_type, cfg, i, hits[:3])
        assert all(hits[j][1] >= hits[j + 1][1] for j in range(len(hits) - 1))

    # Delete-by-document removes exactly that document.
    s.delete_documents(["doc0"])
    assert s.count() == N - N // 5
    hits = s.search(vecs[0], 50)
    assert not any(h[0] in {ids[i] for i in range(0, N, 5)} for h in hits)

    # Reopening from disk gives the same answers.
    before = s.search(vecs[1], 5)
    s.close()
    s2 = make(store_type, cfg)
    s2.open(tmp_path / "s", DIM)
    assert s2.count() == N - N // 5
    assert [h[0] for h in s2.search(vecs[1], 5)] == [h[0] for h in before]
    s2.close()


@pytest.mark.parametrize("metric", ["cosine", "dot", "l2"])
def test_exact_stores_agree(tmp_path, data, metric):
    ids, docs, vecs = data
    q = np.random.default_rng(7).normal(size=DIM).astype(np.float32)
    rankings = {}
    for store_type, cfg in EXACT:
        s = make(store_type, cfg, metric)
        s.open(tmp_path / f"{store_type}-{metric}", DIM)
        s.upsert(ids, docs, vecs)
        hits = s.search(q, 10)
        rankings[store_type] = hits
        s.close()
    ref = rankings["numpy"]
    for name, hits in rankings.items():
        assert [h[0] for h in hits] == [h[0] for h in ref], name
        np.testing.assert_allclose([h[1] for h in hits], [h[1] for h in ref], rtol=1e-3, atol=1e-4,
                                   err_msg=name)


def test_exactness_flags():
    assert make("numpy", {}).is_exact()
    assert make("faiss", {"index_type": "Flat"}).is_exact()
    assert not make("faiss", {"index_type": "HNSW"}).is_exact()
    assert not make("chroma", {}).is_exact()
    assert make("lancedb", {"index_type": "none"}).is_exact()
    assert not make("lancedb", {"index_type": "IVF_PQ"}).is_exact()
