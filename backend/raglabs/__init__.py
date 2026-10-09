"""RAGLabs Python SDK (PRD FR-4.7): test a RAG that's a Python function, with no server, or serve it so the app's
Evaluate → Your RAG can connect to it.

    import raglabs

    @raglabs.system
    def ask(question: str):
        hits = my_retriever(question)
        return {"answer": my_llm(question, hits),
                "contexts": [{"text": h.text, "source": h.file_name} for h in hits]}

    raglabs.evaluate(ask, "eval.csv")   # {'mrr': 0.71, 'hit_at_k': 0.9, ..., 'passed': True}
    raglabs.serve(ask, port=8100)       # then connect http://127.0.0.1:8100 in Evaluate → Your RAG

The function may be sync or async and return the contract dict, a list of contexts (retrieval only) or an
(answer, contexts) tuple; a context may be a plain string. CI: `raglabs eval --system my_rag:ask --set eval.csv`.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


def _backend() -> str:
    """Import the server package (the `app` folder next to this one) as `_raglabs_app`. Never by the name `app`: users'
    projects often have their own `app` package, which would shadow ours on sys.path. Works because the package only
    uses relative imports internally."""
    # ponytail: private alias; renaming the server package to something unique would make this unnecessary
    name = "_raglabs_app"
    if name not in sys.modules:
        init = Path(__file__).resolve().parent.parent / "app" / "__init__.py"
        spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(init.parent)])
        assert spec is not None and spec.loader is not None
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return name


cli = importlib.import_module(f"{_backend()}.cli")
external = importlib.import_module(f"{_backend()}.engine.external")

__all__ = ["aevaluate", "evaluate", "serve", "system"]


def system(fn: external.Ask) -> external.Ask:
    """Mark a function as the RAG to test; `raglabs eval --system my_module` then finds it without a name."""
    fn.__raglabs_system__ = True  # type: ignore[attr-defined]
    return fn


async def aevaluate(fn: external.Ask, eval_set: str, *, top_k: int = 8, min_mrr: float | None = None,
                    min_hit: float | None = None) -> dict[str, Any]:
    """`evaluate` for code that already runs an event loop (Jupyter, async apps)."""
    m = await cli.run_eval(lambda q: external.call(fn, q, top_k), cli.read_set(eval_set), top_k)
    fails = cli.check(m, min_mrr, min_hit)
    return {**m, "passed": not fails, "failures": fails}


def evaluate(fn: external.Ask, eval_set: str, *, top_k: int = 8, min_mrr: float | None = None,
             min_hit: float | None = None) -> dict[str, Any]:
    """Score `fn` on an eval CSV (question, evidence[, document]): Hit@1/3/k, MRR, nDCG, p50/p95 ms, and
    `passed` against the optional thresholds. The same numbers as an HTTP system scored by the app."""
    return asyncio.run(aevaluate(fn, eval_set, top_k=top_k, min_mrr=min_mrr, min_hit=min_hit))


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


def app_for(fn: external.Ask, top_k: int = 8) -> Any:
    """The FastAPI app `serve` runs: POST / {"question"} -> {"answer", "contexts": [{"text", "source", "score"}]}."""
    api = FastAPI(title="RAGLabs system")

    @api.post("/")
    async def ask(body: Question) -> dict[str, Any]:
        try:
            got = await external.call(fn, body.question, top_k)
        except external.ExternalError as e:
            raise HTTPException(500, str(e)) from e
        return {"answer": got["answer"], "contexts": [
            {"text": c["text"], "source": c["external_source"] or None, "score": c["score"]} for c in got["contexts"]]}

    return api


def serve(fn: external.Ask, *, host: str = "127.0.0.1", port: int = 8100, top_k: int = 8) -> None:
    """Expose `fn` over the HTTP contract, so RAGLabs (Evaluate → Your RAG, or `raglabs eval --endpoint`) can score
    it next to your pipelines. Blocks until stopped."""
    import uvicorn

    uvicorn.run(app_for(fn, top_k), host=host, port=port)
