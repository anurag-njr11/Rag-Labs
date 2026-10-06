import json

import pytest

import app.nodes  # noqa: F401  (registers node types)
from app.core.node import SLOTS, field_effects, get_spec
from app.core.pipeline import (
    PipelineError, catalog, diff_pipelines, index_config_hash, recommended_pipeline, validate_pipeline,
)


def test_every_slot_has_types_and_recommended_is_valid():
    cfg = recommended_pipeline()
    assert list(cfg) == [s.name for s in SLOTS]
    assert cfg["vector_store"]["type"] == "faiss"


def test_catalog_is_json_and_complete():
    cat = catalog()
    json.dumps(cat)
    stores = {t["type"] for s in cat if s["slot"] == "vector_store" for t in s["types"]}
    assert stores == {"numpy", "faiss", "chroma", "qdrant", "lancedb"}


def test_validation_rejects_unknowns():
    cfg = recommended_pipeline()
    with pytest.raises(PipelineError) as e:
        validate_pipeline({**cfg, "bogus": {"type": "x"}})
    assert any(err["slot"] == "bogus" for err in e.value.errors)
    with pytest.raises(PipelineError):
        validate_pipeline({**cfg, "chunk": {"type": "no_such_chunker"}})
    with pytest.raises(PipelineError):
        validate_pipeline({**cfg, "chunk": {**cfg["chunk"], "not_a_field": 1}})
    with pytest.raises(PipelineError):
        validate_pipeline({**cfg, "chunk": {**cfg["chunk"], "overlap": 5000, "size": 100}})


def test_validation_fills_defaults():
    cfg = recommended_pipeline()
    out = validate_pipeline({**cfg, "chunk": {"type": "fixed"}})
    assert out["chunk"] == {"type": "fixed", "size": 1000, "overlap": 150, "unit": "chars"}


def test_instant_changes_keep_index_hash():
    cfg = recommended_pipeline()
    h = index_config_hash(cfg)
    changed = json.loads(json.dumps(cfg))
    changed["retrieve"]["top_k"] = 3
    changed["generate"]["temperature"] = 0.9
    changed["vector_store"]["ef_search"] = 500     # store field marked instant
    changed["embed"]["batch_size"] = 8             # embed field marked instant
    changed["embed"]["query_prefix"] = "q: "       # query-side only
    assert index_config_hash(changed) == h


def test_rebuild_changes_change_index_hash():
    cfg = recommended_pipeline()
    h = index_config_hash(cfg)
    for slot, key, val in [("chunk", "size", 500), ("embed", "model", "BAAI/bge-base-en-v1.5"),
                           ("vector_store", "index_type", "HNSW"), ("parse", "strip_headers_footers", False)]:
        changed = json.loads(json.dumps(cfg))
        changed[slot][key] = val
        assert index_config_hash(validate_pipeline(changed)) != h, (slot, key)
    changed = json.loads(json.dumps(cfg))
    changed["vector_store"] = {"type": "chroma"}
    assert index_config_hash(validate_pipeline(changed)) != h


def test_diff_reports_effects():
    a = recommended_pipeline()
    b = json.loads(json.dumps(a))
    b["retrieve"]["top_k"] = 3
    b["chunk"]["size"] = 400
    d = {(c["slot"], c["field"]): c["effect"] for c in diff_pipelines(a, b)}
    assert d == {("retrieve", "top_k"): "instant", ("chunk", "size"): "rebuild"}


def test_field_effect_overrides():
    eff = field_effects("vector_store", get_spec("vector_store", "faiss").cls.Config)
    assert eff["index_type"] == "rebuild" and eff["ef_search"] == "instant" and eff["nprobe"] == "instant"


def test_old_versions_missing_new_fields_diff_cleanly():
    """A config saved before a field existed must not show a phantom change."""
    new = recommended_pipeline()
    old = json.loads(json.dumps(new))
    del old["retrieve"]["pin_definitions"]      # added after v1 was saved
    del old["generate"]["reasoning_effort"]
    assert diff_pipelines(old, new) == []
    assert diff_pipelines(new, old) == []


def test_node_revision_changes_index_hash(monkeypatch):
    cfg = recommended_pipeline()
    cls = get_spec("parse", cfg["parse"]["type"]).cls
    h = index_config_hash(cfg)
    monkeypatch.setattr(cls, "revision", cls.revision + 1)
    assert index_config_hash(cfg) != h


def test_strip_inline_html():
    from app.ingest.loaders import strip_inline_html

    assert strip_inline_html("after the 4<sup>th</sup> semester") == "after the 4th semester"
    assert strip_inline_html("<mark>Guidelines for <b>UG</b></mark>") == "Guidelines for **UG**"
    assert strip_inline_html("| a<br>b | c |") == "| a b | c |"
    assert strip_inline_html("cut <mark>off") == "cut off"
    assert strip_inline_html("<class 'int'> and <div>") == "<class 'int'> and <div>"


# --- semantic chunker ---------------------------------------------------------

TOPICS = ("Cats purr when content. Cats chase mice at night. Cats sleep most of the day. "
          "Rockets burn liquid fuel. Rockets reach orbit in minutes. Rockets need powerful engines.")


def _topic_vectors(texts):
    import numpy as np
    return np.array([[1.0, 0.0] if "cat" in t.lower() else [0.0, 1.0] for t in texts], dtype=np.float32)


def test_semantic_chunker_splits_at_topic_change(monkeypatch):
    from app.nodes import chunk as C
    monkeypatch.setattr(C, "embed_sentences", lambda model, texts: _topic_vectors(texts))
    chunker = C.SemanticChunker({"size": 2000, "overlap": 0, "min_chunk_size": 0})
    chunks = chunker.chunk([{"page": 1, "text": TOPICS}])
    assert [c["text"].split()[0] for c in chunks] == ["Cats", "Rockets"]
    assert "Rockets" not in chunks[0]["text"] and "Cats" not in chunks[1]["text"]
    assert chunker.chunk([{"page": 1, "text": TOPICS}]) == chunks  # deterministic
    # Max size still caps a topic group.
    small = C.SemanticChunker({"size": 60, "overlap": 0, "min_chunk_size": 0}).chunk([{"page": 1, "text": TOPICS}])
    assert len(small) > 2 and all(len(c["text"]) <= 60 for c in small)


def test_semantic_chunker_config_feeds_index_hash():
    cfg = validate_pipeline({**recommended_pipeline(), "chunk": {"type": "semantic"}})
    h = index_config_hash(cfg)
    for key, val in [("breakpoint_percentile", 80), ("min_chunk_size", 300), ("size", 600),
                     ("model", "BAAI/bge-base-en-v1.5")]:
        assert index_config_hash(validate_pipeline({**cfg, "chunk": {**cfg["chunk"], key: val}})) != h, key


def test_query_expansion_and_context_window_are_instant():
    cfg = recommended_pipeline()
    assert cfg["retrieve"]["query_expansion"] == "none" and cfg["retrieve"]["context_window"] == 0
    changed = {**cfg, "retrieve": {**cfg["retrieve"], "query_expansion": "hyde", "context_window": 2}}
    assert index_config_hash(validate_pipeline(changed)) == index_config_hash(cfg)
