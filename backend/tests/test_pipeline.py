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
