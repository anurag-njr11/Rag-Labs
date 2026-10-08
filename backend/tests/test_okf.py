"""OKF bundles (FR-3.18, 3.20) and metadata-aware retrieval (FR-3.19)."""

import io
import zipfile
from datetime import date

import httpx

from app import db
from app.core.node import RunContext
from app.core.pipeline import validate_pipeline
from app.engine import okf, retrieval
from app.ingest import builder
from app.ingest.documents import create_document, okf_from_front_matter
from app.ingest.loaders import front_matter
from test_eval import project  # noqa: F401  (fixture)
from test_retrieval import _cfg

SETUP = b"""---
type: Guide
status: deprecated
verified: human:alice@2026-05-01
sources: [https://wiki.example/setup]
stale_after: 2099-01-01
generated: 2026-06-01T10:00:00Z
---
# Setup

Install the agent with the installer, then see [the FAQ](../faq.md) and [a missing page](nowhere.md).
"""
FAQ = b"---\ntype: FAQ\n---\n# FAQ\n\nThe agent reports every five minutes.\n"


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_trust_tiers_and_front_matter_fields():
    assert [okf.trust_tier(v) for v in (True, date(2026, 1, 1), "human:a", "process:ci", "agent:x", "2026-01-02",
                                        "someone", None, False)] == [
        "human", "human", "human", "process", "agent", "human", "unverified", "unverified", "unverified"]
    meta = okf_from_front_matter(SETUP)
    assert meta["type"] == "Guide" and meta["verified"] == "human:alice@2026-05-01"
    assert meta["generated"].startswith("2026-06-01") and meta["sources"] == ["https://wiki.example/setup"]


def test_policy_drops_stale_demotes_deprecated_prefers_human():
    fused = [("stale", 0.9), ("dep", 0.8), ("agent", 0.5), ("human", 0.5), ("plain", 0.3)]
    meta = {"stale": {"stale_after": "2020-01-01"}, "dep": {"status": "deprecated"},
            "agent": {"verified": "agent:w"}, "human": {"verified": True}}
    out, counts = okf.apply_policy(fused, meta, "2026-10-07")
    assert [c for c, _ in out] == ["human", "agent", "dep", "plain"] and counts == {"dropped": 1, "demoted": 1}


async def test_import_bundle_keeps_paths_and_skips_non_markdown(project):  # noqa: F811
    data = _zip({"kb/guides/setup.md": SETUP, "kb/faq.md": FAQ, "kb/refs/rates.csv": b"a,b\n1,2\n",
                 "kb/.drafts/x.md": b"# hidden", "__MACOSX/kb/._faq.md": b"junk"})
    out = await okf.import_bundle("p", data)
    assert sorted(d["filename"] for d in out["created"]) == ["faq.md", "guides__setup.md"]
    assert [s["path"] for s in out["skipped"]] == ["kb/refs/rates.csv"] and not out["errors"]
    row = await db.fetch_one("SELECT o.metadata FROM documents d JOIN document_okf o ON o.document_id = d.id"
                             " WHERE d.filename='guides__setup.md'")
    assert db.loads(row["metadata"])["status"] == "deprecated"
    assert (await okf.import_bundle("p", data))["duplicates"]  # same bytes → no new documents


async def test_policy_in_retrieval(project):  # noqa: F811
    await create_document("p", "retired.md", b"---\nstale_after: 2020-01-01\n---\n# Retired\n\n"
                                             b"Failed uploads are retried nine times in the retired design.\n")
    plain = _cfg("numpy")
    build = await builder.sync_build(project, plain)
    q = "how many times are failed uploads retried"
    before = await retrieval.retrieve(RunContext(), build=build, cfg=plain, question=q)
    assert any(r["document"] == "retired.md" for r in before)
    cfg = validate_pipeline({**plain, "retrieve": {**plain["retrieve"], "okf_policy": True}})
    ctx = RunContext()
    after = await retrieval.retrieve(ctx, build=build, cfg=cfg, question=q)
    assert after and all(r["document"] != "retired.md" for r in after)
    (step,) = [e for e in ctx.events if e.step == "okf_policy"]
    assert step.payload["dropped"] >= 1


async def test_export_bundle_round_trips(project):  # noqa: F811
    from app.main import app

    await okf.import_bundle("p", _zip({"guides/setup.md": SETUP, "faq.md": FAQ}))
    await builder.sync_build(project, _cfg("numpy"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.get("/api/projects/p/documents/okf-export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"index.md", "guides/setup.md", "faq.md", "uploads.md"} <= names
    setup = z.read("guides/setup.md").decode()
    fm = front_matter(setup)
    assert fm["type"] == "Guide" and fm["trust"] == "human" and fm["status"] == "deprecated"
    assert fm["sources"] == ["https://wiki.example/setup"] and "Install the agent" in setup
    assert setup.count("---\n") == 2  # one front-matter block: the original was replaced, not kept
    assert front_matter(z.read("uploads.md").decode())["sources"] == ["upload:uploads.md"]
    # The exported bundle imports cleanly into another project, metadata intact.
    async with db.tx() as tx:
        await tx.execute("INSERT INTO projects (id, name, created_at) VALUES ('p2', 'P2', ?)", (db.now_iso(),))
    out = await okf.import_bundle("p2", r.content)
    assert not out["errors"] and len(out["created"]) == len(names) - 1 + 1  # every .md incl. index.md
    row = await db.fetch_one("SELECT o.metadata FROM documents d JOIN document_okf o ON o.document_id = d.id"
                             " WHERE d.project_id='p2' AND d.filename='guides__setup.md'")
    assert db.loads(row["metadata"])["verified"] == "human:alice@2026-05-01"


async def test_import_rejects_non_zip_and_api(project):  # noqa: F811
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        bad = await c.post("/api/projects/p/documents/okf?build=false", files={"file": ("kb.zip", b"not a zip")})
        assert bad.status_code == 422 and "zip" in bad.json()["detail"]
        ok = await c.post("/api/projects/p/documents/okf?build=false", files={"file": ("kb.zip", _zip({"a/faq.md": FAQ}))})
        assert ok.status_code == 201 and ok.json()["created"][0]["filename"] == "faq.md" and ok.json()["job_id"] is None


async def test_metadata_api_keeps_provenance_and_type(project):  # noqa: F811
    from app.main import app

    doc = await db.fetch_one("SELECT id FROM documents WHERE filename='uploads.md'")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.patch(f"/api/projects/p/documents/{doc['id']}/metadata",
                          json={"type": "Runbook", "verified": "process:ci-docs", "generated": "2026-01-01T00:00:00Z"})
        assert r.status_code == 200
        o = r.json()["okf"]
        assert (o["type"], o["verified"], o["generated"]) == ("Runbook", "process:ci-docs", "2026-01-01T00:00:00Z")
        r = await c.patch(f"/api/projects/p/documents/{doc['id']}/metadata", json={"verified": "2026-05-01"})
        assert r.json()["okf"]["verified"] == "2026-05-01" and okf.trust_tier(r.json()["okf"]["verified"]) == "human"
