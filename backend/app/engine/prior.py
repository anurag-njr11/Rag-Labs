"""Config prior (FR-3.27): predict a winning configuration from a corpus fingerprint.

Every finished sweep logs an anonymised corpus fingerprint and its winning settings (FR-2.35). For a
new corpus, the fingerprints of sweeps on this install are weighted by similarity, and for each setting
those sweeps compared, the winning values vote:

    confidence(value) = vote share × (1 − e^(−n_eff / 3)) × mean similarity of the voters

— so it rises with agreement, with the amount of similar evidence, and with how similar it is. With
no sweep history the honest answer is the rule-based recommender, labelled as rules, not measurements.
Either way the prediction comes with the sweep that would verify it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .. import db
from ..core.pipeline import validate_pipeline, with_defaults
from .sweep import SweepError, apply_override, corpus_fingerprint

MIN_SIMILARITY = 0.6


def features(fp: dict[str, Any]) -> list[float]:
    """A fingerprint as numbers in [0, 1]: size, structure, code, tables, OCR need."""
    return [
        min(1.0, math.log10(1 + float(fp.get("total_char_count") or 0)) / 7),
        min(1.0, float(fp.get("avg_structure_density") or 0) * 4),
        min(1.0, float(fp.get("avg_code_density") or 0) * 2),
        min(1.0, math.log10(1 + float(fp.get("total_table_count") or 0)) / 3),
        1.0 if fp.get("ocr_needed") else 0.0,
        min(1.0, math.log10(1 + float(fp.get("documents") or 0)) / 3),
    ]


def similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    fa, fb = features(a), features(b)
    return round(1 - math.dist(fa, fb) / math.sqrt(len(fa)), 4)


def predict(fp: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per swept setting, the best-supported winning value among similar corpora."""
    votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    voters: dict[str, list[float]] = defaultdict(list)
    values: dict[tuple[str, str], Any] = {}
    for r in rows:
        sim = similarity(fp, r["fingerprint"])
        if sim < MIN_SIMILARITY:
            continue
        for path, value in (r["winner"].get("overrides") or {}).items():
            key = repr(value)
            votes[path][key] += sim
            values[(path, key)] = value
            voters[path].append(sim)
    out = []
    for path, vs in votes.items():
        key, weight = max(vs.items(), key=lambda kv: kv[1])
        share = weight / sum(vs.values())
        n_eff = len(voters[path])
        conf = share * (1 - math.exp(-n_eff / 3)) * (sum(voters[path]) / n_eff)
        out.append({"path": path, "value": values[(path, key)], "confidence": round(conf, 2), "votes": round(share, 2),
                    "sweeps": n_eff, "mean_similarity": round(sum(voters[path]) / n_eff, 2)})
    return sorted(out, key=lambda s: -s["confidence"])


async def for_project(project_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    fp = await corpus_fingerprint(project_id)
    rows = [{"fingerprint": db.loads(r["fingerprint"], {}), "winner": db.loads(r["winner"], {})}
            for r in await db.fetch_all("SELECT fingerprint, winner FROM sweep_fingerprints")]
    base = with_defaults(cfg)
    suggestions = predict(fp, rows)
    source = "prior"
    if not suggestions:
        from ..core.recommender import Recommender
        from ..ingest.document_analyzer import DocumentMetadata, aggregate_corpus_metadata

        metas = await db.fetch_all("SELECT metadata FROM document_metadata WHERE project_id=?", (project_id,))
        rec_cfg, reasons = Recommender.recommend(aggregate_corpus_metadata(
            [DocumentMetadata(**db.loads(m["metadata"], {})) for m in metas]))
        source = "rules"
        for slot in ("chunk", "retrieve", "rerank"):
            for field in ("type", "size") if slot == "chunk" else ("type",):
                v = rec_cfg.get(slot, {}).get(field)
                if v is not None and base.get(slot, {}).get(field) != v:
                    suggestions.append({"path": f"{slot}.{field}", "value": v, "confidence": None,
                                        "reason": reasons.get(slot, "")})
    predicted, applied = base, []
    for s in suggestions:
        if base.get(s["path"].split(".")[0], {}).get(s["path"].split(".")[1]) == s["value"]:
            s["current"] = True  # already what you have
            continue
        try:
            trial = {k: dict(v) for k, v in predicted.items()}
            apply_override(trial, s["path"], s["value"])
            predicted = validate_pipeline(trial)
            applied.append(s)
        except (SweepError, ValueError):
            s["skipped"] = "doesn't fit the current configuration"
    return {
        "source": source,
        "fingerprint": fp,
        "history": len(rows),
        "suggestions": suggestions,
        "config": predicted,
        # The sweep that would check it: each predicted change against what you have now.
        "verify_axes": [{"path": s["path"], "values": [base[s["path"].split(".")[0]].get(s["path"].split(".")[1]), s["value"]]}
                        for s in applied][:4],
    }
