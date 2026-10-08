"""`raglabs` command line: run the app, or gate CI on an external RAG's retrieval quality (PRD FR-4.6).

    raglabs serve [--host H] [--port P]
    raglabs eval --endpoint URL --set eval.csv [--min-mrr 0.6] [--min-hit 0.8] [--header "Authorization: Bearer $T"]

`eval` needs no project or database. The CSV has columns `question` and `evidence` (a verbatim quote that
answers it) and optionally `document` (the file name; when the system names a source it must match).
Exit code: 0 = thresholds met, 1 = a threshold missed, 2 = bad input or the system could not be reached.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from typing import Any

from .core import evalmetrics as M
from .engine import external


def die(msg: str) -> Any:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def read_set(path: str) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    items = [{"question": r["question"], "evidence": r["evidence"], "filename": r.get("document") or None}
             for r in rows if r.get("question") and r.get("evidence") and r.get("valid", "yes").lower() not in ("no", "false", "0")]
    if not items:
        die("the CSV needs rows with `question` and `evidence` columns")
    return items


async def run_eval(cfg: external.ExternalConfig, items: list[dict[str, Any]]) -> dict[str, Any]:
    ranks: list[int | None] = []
    ms: list[float] = []
    for i, item in enumerate(items, start=1):
        try:
            got = await external.query(cfg, item["question"])
        except external.ExternalError as e:
            die(f"question {i}: {e}")
        ranks.append(M.first_hit_rank(got["contexts"], item))
        ms.append(got["ms"])
    out = M.summarize(ranks, cfg.top_k)
    out["p50_ms"], out["p95_ms"] = (round(M.percentile(ms, q), 1) for q in (0.5, 0.95))
    return out


def check(m: dict[str, Any], min_mrr: float | None, min_hit: float | None) -> list[str]:
    fails = []
    if min_mrr is not None and m["mrr"] < min_mrr:
        fails.append(f"MRR {m['mrr']:.3f} < {min_mrr}")
    if min_hit is not None and m["hit_at_k"] < min_hit:
        fails.append(f"Hit@{m['k']} {m['hit_at_k']:.3f} < {min_hit}")
    return fails


def cmd_eval(a: argparse.Namespace) -> int:
    headers = {}
    for h in a.header:
        name, sep, value = h.partition(":")
        if not sep:
            die(f"--header must look like 'Name: value', got {h!r}")
        headers[name.strip()] = value.strip()
    try:
        cfg = external.ExternalConfig(url=a.endpoint, headers=headers, question_field=a.question_field,
                                      answer_path=a.answer_path, contexts_path=a.contexts_path, text_path=a.text_path,
                                      source_path=a.source_path, top_k=a.top_k, timeout_s=a.timeout)
    except ValueError as e:
        die(str(e))
    m = asyncio.run(run_eval(cfg, read_set(a.set)))
    fails = check(m, a.min_mrr, a.min_hit)
    if a.json:
        print(json.dumps({**m, "passed": not fails, "failures": fails}))
    else:
        print(f"{m['n']} questions · Hit@1 {m['hit_at_1']:.2f} · Hit@3 {m['hit_at_3']:.2f} · Hit@{m['k']} {m['hit_at_k']:.2f}"
              f" · MRR {m['mrr']:.3f} · nDCG@{m['k']} {m['ndcg_at_k']:.3f} · p50 {m['p50_ms']:.0f} ms · p95 {m['p95_ms']:.0f} ms")
        print("FAIL: " + "; ".join(fails) if fails else "PASS")
    return 1 if fails else 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=a.host, port=a.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="raglabs", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the RAGLabs backend")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    e = sub.add_parser("eval", help="score an external RAG endpoint on an eval CSV; exit 1 below the thresholds")
    e.add_argument("--endpoint", required=True)
    e.add_argument("--set", required=True, help="eval CSV: question, evidence[, document]")
    e.add_argument("--min-mrr", type=float)
    e.add_argument("--min-hit", type=float, help="minimum Hit@top-k")
    e.add_argument("--header", action="append", default=[], help="'Name: value', repeatable")
    e.add_argument("--question-field", default="question")
    e.add_argument("--answer-path", default="answer")
    e.add_argument("--contexts-path", default="contexts")
    e.add_argument("--text-path", default="text")
    e.add_argument("--source-path", default="source")
    e.add_argument("--top-k", type=int, default=8)
    e.add_argument("--timeout", type=float, default=30)
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
