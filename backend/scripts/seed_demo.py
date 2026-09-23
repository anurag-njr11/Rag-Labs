"""Seed a demo project: the Pydantic v2 documentation, pinned to a release tag.

Runs against the live API (start the backend first), so it exercises exactly
the path the UI uses. Safe to re-run: an existing "Pydantic Docs" project is
reused and duplicate documents are skipped.

    uv run python scripts/seed_demo.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    api = args.api.rstrip("/") + "/api"

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
            r = c.get(RAW + path)
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
            with c.stream("GET", f"{api}/jobs/{job_id}/events", timeout=None) as s:
                for line in s.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:])
                    if ev["type"] == "progress":
                        print(f"  {ev['stage']:9} {ev['message']}")
                    elif ev["type"] == "failed":
                        print(f"Build failed: {ev['error']}")
                        return 1
                    elif ev["type"] == "done":
                        b = ev["result"]["build"]
                        print(f"Index ready: {b['chunk_count']} chunks in {b['stats'].get('seconds', 0)}s")
                        break
        else:
            print("Index already up to date.")

        print(f"\nOpen http://localhost:5173/projects/{project['id']}/playground and try:")
        print('  • "How do I make a field optional with a default?"')
        print("  • paste: Input should be a valid integer, unable to parse string as an integer"
              " [type=int_parsing, input_value='abc', input_type=str]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
