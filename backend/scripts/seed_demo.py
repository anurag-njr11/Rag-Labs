"""Seed a demo project: the Pydantic v2 documentation, pinned to a release tag.

Runs against the live API (start the backend first), so it exercises exactly
the path the UI uses. Then, if an LLM key is configured (Phase 2): generates an
eval set, scores the active version and runs an Auto-Optimize sweep.

Safe to re-run: the "Pydantic Docs" project, duplicate documents, a ready eval
set, an up-to-date eval run and a finished (or running) sweep are all reused.

    uv run python scripts/seed_demo.py [--api http://127.0.0.1:8000] [--web http://localhost:5173] [--no-eval]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

TAG = "v2.13.5"
RAW = f"https://raw.githubusercontent.com/pydantic/pydantic/{TAG}/docs/"
FILES = [
    "concepts/models.md",
    "concepts/fields.md",
    "concepts/validators.md",
    "concepts/config.md",
    "concepts/types.md",
    "concepts/serialization.md",
    "concepts/json_schema.md",
    "errors/errors.md",
    "errors/validation_errors.md",
    "errors/usage_errors.md",
]
NAME = "Pydantic Docs"
DESCRIPTION = f"Pydantic {TAG} documentation — models, fields, validators and the error reference."

# Phase 2 demo: 2 x 2 x 2 = 8 cells, all query-time settings, so every cell reuses one index.
EVAL_SIZE = 30
AXES = [
    {"path": "retrieve.type", "values": ["hybrid", "fused"]},
    {"path": "retrieve.top_k", "values": [5, 10]},
    {"path": "rerank.type", "values": ["none", "cross_encoder"]},
]


def follow(c: httpx.Client, api: str, job_id: str) -> dict | None:
    """Stream a job's SSE progress; return its result, or None if it failed."""
    last = None
    with c.stream("GET", f"{api}/jobs/{job_id}/events", timeout=None) as s:
        for line in s.iter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if ev["type"] == "progress":
                # Per-question ticks repeat the same stage/message: print only what changed.
                if (ev["stage"], ev["message"]) != last:
                    last = (ev["stage"], ev["message"])
                    print(f"  {ev['stage']:11} {ev['message']}".rstrip())
            elif ev["type"] == "log" and ev["level"] != "info":
                print(f"  ! {ev['message']}")
            elif ev["type"] == "failed":
                print(f"  failed: {ev['error']}")
                return None
            elif ev["type"] == "done":
                return ev["result"] or {}
    return None


def running_job(c: httpx.Client, api: str, pid: str, kind: str) -> str | None:
    return next((j["id"] for j in c.get(f"{api}/projects/{pid}/jobs").json() if j["kind"] == kind), None)


def label(cell: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in cell["overrides"].items())


def phase2(c: httpx.Client, api: str, pid: str, web: str) -> int:
    providers = c.get(f"{api}/health").json()["providers"]
    if not any(providers.values()):
        print("\nNo LLM API key configured (GEMINI_API_KEY / NVIDIA_API_KEY in .env) —"
              " skipping the eval set and Auto-Optimize sweep.")
        return 0
    ev = f"{api}/projects/{pid}/eval"
    active = c.get(f"{api}/projects/{pid}").json()["active_version"]

    # 1. Eval set: reuse the newest ready one (or wait for one being generated).
    sets = c.get(f"{ev}/sets").json()
    s = next((x for x in sets if x["status"] == "ready"), None)
    if s is None:
        job = running_job(c, api, pid, "evalset")
        if job:
            print("\nWaiting for the eval set already being generated…")
        else:
            print(f"\nGenerating an eval set ({EVAL_SIZE} questions written from the documents)…")
            job = c.post(f"{ev}/sets", json={"size": EVAL_SIZE}).json()["job_id"]
        if follow(c, api, job) is None:
            return 1
        s = next(x for x in c.get(f"{ev}/sets").json() if x["status"] == "ready")
    else:
        print(f"\nReusing eval set {s['id'][:8]}")
    st = s["stats"]
    print(f"Eval set: {st.get('kept')} questions kept of {st.get('generated')} generated"
          f" ({st.get('too_generic', 0)} too generic, {st.get('bad_evidence', 0)} bad evidence)")

    # 2. Score the active version (reuse a run of this version on this revision of the set).
    runs = c.get(f"{ev}/runs", params={"set_id": s["id"]}).json()
    run = next((r for r in reversed(runs) if r["version_id"] == active["id"] and r["status"] == "ready"
                and r.get("set_revision") == s.get("revision")), None)
    if run is None:
        print(f"Scoring v{active['version']} on the eval set…")
        res = c.post(f"{ev}/sets/{s['id']}/runs", json={}).json()
        if follow(c, api, res["job_id"]) is None:
            return 1
        run = c.get(f"{ev}/runs/{res['run']['id']}").json()
    else:
        print(f"Reusing eval run of v{active['version']}")
    m = run["metrics"]
    print(f"v{active['version']}: Hit@1 {m['hit_at_1']:.2f} · Hit@{m['k']} {m['hit_at_k']:.2f} · MRR {m['mrr']:.3f}"
          f" · nDCG@{m['k']} {m.get('ndcg_at_k', 0):.3f} · {m['ctx_tokens']} ctx tokens/q"
          f" · p50 {m['p50_ms']} ms · p95 {m.get('p95_ms')} ms")
    misses = {k: v for k, v in m["diagnoses"].items() if v}
    print("  misses: " + (", ".join(f"{k} {v}" for k, v in misses.items()) if misses else "none"))

    # 3. Auto-Optimize sweep: reuse a ready/running one over the same set and axes.
    sweep = next((x for x in c.get(f"{ev}/sweeps").json() if x["eval_set_id"] == s["id"]
                  and x["axes"] == AXES and x["status"] in ("ready", "running")), None)
    if sweep is None or sweep["status"] == "running":
        job = running_job(c, api, pid, "sweep") if sweep else None
        if job is None:
            print(f"\nAuto-Optimize sweep: {len(AXES)} axes → 8 configurations, then answer-grading the best 2…")
            res = c.post(f"{ev}/sweeps", json={"set_id": s["id"], "axes": AXES, "auto_optimize": True}).json()
            sweep, job = res["sweep"], res["job_id"]
        else:
            print("\nWaiting for the sweep already running…")
        if follow(c, api, job) is None:
            return 1
        sweep = c.get(f"{ev}/sweeps/{sweep['id']}").json()
    else:
        print(f"\nReusing sweep {sweep['id'][:8]}")

    # Leaderboard order = the UI's: MRR, then fewer context tokens.
    cells = sorted((x for x in sweep["cells"] if x["status"] == "ready"),
                   key=lambda x: (-x["metrics"]["mrr"], x["metrics"]["ctx_tokens"]))
    print("Leaderboard (MRR · Hit@k · ctx tokens · answers correct):")
    for x in cells:
        mm, a = x["metrics"], x["metrics"].get("answers")
        ans = f"{a['correct_rate']:.0%}" if a and a.get("n") else "—"
        print(f"  {'P' if x.get('pareto') else ' '} {mm['mrr']:.3f} · {mm['hit_at_k']:.2f} · {mm['ctx_tokens']:>5}"
              f" · {ans:>4}  {label(x)}")
    if cells:
        print(f"Winner: {label(cells[0])} (MRR {cells[0]['metrics']['mrr']:.3f}; P = on the Pareto frontier)")

    print(f"\nEvaluate tab: {web}/projects/{pid}/evaluate   (promote the winner from the leaderboard)")
    print(f"Health tab:   {web}/projects/{pid}/health")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--web", default="http://localhost:5173", help="frontend URL, for the printed links")
    ap.add_argument("--no-eval", action="store_true", help="Phase 1 only: skip the eval set and sweep")
    args = ap.parse_args()
    api = args.api.rstrip("/") + "/api"
    web = args.web.rstrip("/")
    t0 = time.monotonic()

    with httpx.Client(timeout=120) as c:
        try:
            c.get(f"{api}/health").raise_for_status()
        except httpx.HTTPError:
            print(f"Backend not reachable at {args.api}. Start it first:  uv run uvicorn app.main:app")
            return 1

        project = next((p for p in c.get(f"{api}/projects").json() if p["name"] == NAME), None)
        if project is None:
            project = c.post(f"{api}/projects", json={"name": NAME, "description": DESCRIPTION}).json()
            print(f"Created project {NAME!r}")
        else:
            print(f"Reusing project {NAME!r}")

        files = []
        for path in FILES:
            for attempt in range(3):  # raw.githubusercontent.com sometimes drops a connection mid-body
                try:
                    r = c.get(RAW + path)
                    break
                except httpx.HTTPError as e:
                    err = e
            else:
                print(f"  skip {path}: {err}")
                continue
            if r.status_code != 200:
                print(f"  skip {path}: HTTP {r.status_code}")
                continue
            # Prefix the folder so errors/errors.md and concepts/... stay distinguishable.
            files.append(("files", (path.replace("/", "__"), r.content, "text/markdown")))
            print(f"  downloaded {path} ({len(r.content) // 1024} KB)")

        res = c.post(f"{api}/projects/{project['id']}/documents", files=files).json()
        print(f"Uploaded {len(res['created'])} new, {len(res['duplicates'])} already present,"
              f" {len(res['errors'])} rejected")
        for e in res["errors"]:
            print(f"  ! {e['filename']}: {e['error']}")

        job_id = res.get("job_id") or c.get(f"{api}/projects/{project['id']}").json()["index"]["job_id"]
        if job_id:
            print("Building the index (the first run downloads a ~70 MB embedding model)…")
            result = follow(c, api, job_id)
            if result is None:
                print("Build failed.")
                return 1
            b = result["build"]
            print(f"Index ready: {b['chunk_count']} chunks in {b['stats'].get('seconds', 0)}s")
        else:
            print("Index already up to date.")

        print(f"\nOpen {web}/projects/{project['id']}/playground and try:")
        print('  • "How do I make a field optional with a default?"')
        print("  • paste: Input should be a valid integer, unable to parse string as an integer"
              " [type=int_parsing, input_value='abc', input_type=str]")

        rc = 0 if args.no_eval else phase2(c, api, project["id"], web)
    print(f"\nDone in {time.monotonic() - t0:.0f}s.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
