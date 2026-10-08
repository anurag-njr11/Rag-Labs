"""Domain embedding adapter (FR-3.10), trained on the auto-generated eval set.

Domain adaptation needs labelled (query, relevant passage) pairs — which nobody has, which is why
almost nobody does it. The eval generator produces exactly those: each question's positives are the
chunks holding its evidence quote.

The adapter is a linear map on the *query* side only: q' = W q, with W initialised to the identity and
document vectors untouched, so it needs no re-index and is an instant setting. Training minimises a
softmax contrastive loss over every chunk of the corpus (multi-positive), plus λ‖W − I‖² to stay near
the identity, with Adam — NumPy only, CPU, seconds. λ is chosen by 3-fold cross-validation within the
training questions; when no λ beats the plain embedder the largest wins, so by default it does no harm.

Honest reporting: W is first fitted on 75% of the questions and scored before/after on the 25% it never
saw (dense-only ranking: Recall@5, MRR). Then it is refitted on all of them; that is the saved adapter.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from .. import db, vault
from ..config import get_settings
from ..core import evalmetrics as M
from ..core.node import build_node
from ..core.pipeline import with_defaults
from ..ingest.jobs import Job
from . import evaluate

TAU = 0.05  # softmax temperature over cosine scores
LAMBDA = 0.05  # pull towards the identity
STEPS = 300
LR = 2e-3
HOLDOUT = 0.25
MIN_QUESTIONS = 8


def adapter_path(project_id: str, adapter_id: str) -> Path:
    return get_settings().data_dir / "adapters" / project_id / f"{adapter_id}.npy"


_loaded: dict[str, np.ndarray] = {}


def load(project_id: str, adapter_id: str) -> np.ndarray | None:
    """The adapter matrix, cached; None if it doesn't exist (deleted, or another project's)."""
    key = f"{project_id}/{adapter_id}"
    if key not in _loaded:
        p = adapter_path(project_id, adapter_id)
        if not p.exists():
            return None
        _loaded[key] = np.load(p)
    return _loaded[key]


def apply(w: np.ndarray, q: np.ndarray) -> np.ndarray:
    """q' = W q, rescaled to q's length so L2 / dot stores rank on the same scale (cosine is unaffected)."""
    out = w @ q.astype(np.float32)
    n = np.linalg.norm(out)
    return (out * (np.linalg.norm(q) / n) if n else out).astype(np.float32)


def _norm(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)


def fit(q: np.ndarray, c: np.ndarray, pos: list[list[int]], steps: int = STEPS, lr: float = LR,
        lam: float = LAMBDA, tau: float = TAU) -> np.ndarray:
    """Adam on mean softmax cross-entropy over all chunks (uniform over each question's positives)."""
    n, d = q.shape
    q, c = _norm(q).astype(np.float64), _norm(c).astype(np.float64)
    y = np.zeros((n, len(c)))
    for i, p in enumerate(pos):
        y[i, p] = 1.0 / len(p)
    w, eye = np.eye(d), np.eye(d)
    m1, m2 = np.zeros_like(w), np.zeros_like(w)
    for t in range(1, steps + 1):
        z = (q @ w.T) @ c.T / tau
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=1, keepdims=True)
        g = (c.T @ ((p - y) / tau).T @ q) / n + 2 * lam * (w - eye)
        m1 = 0.9 * m1 + 0.1 * g
        m2 = 0.999 * m2 + 0.001 * g * g
        w -= lr * (m1 / (1 - 0.9 ** t)) / (np.sqrt(m2 / (1 - 0.999 ** t)) + 1e-8)
    return w.astype(np.float32)


def rank_metrics(q: np.ndarray, c: np.ndarray, pos: list[list[int]], w: np.ndarray | None = None,
                 k: int = 5) -> dict[str, float]:
    """Dense-only brute-force ranking of every chunk: Recall@k (a positive in the top k) and MRR."""
    if not len(q):
        return {"recall_at_k": 0.0, "mrr": 0.0, "n": 0}
    qq = _norm(q) if w is None else _norm(q @ w.T)
    s = qq @ _norm(c).T
    ranks = []
    for i, p in enumerate(pos):
        order = np.argsort(-s[i], kind="stable")
        ranks.append(int(np.flatnonzero(np.isin(order, p))[0]) + 1)
    return {"recall_at_k": round(sum(r <= k for r in ranks) / len(ranks), 4),
            "mrr": round(sum(1 / r for r in ranks) / len(ranks), 4), "n": len(ranks)}


LAMBDAS = (0.01, 0.1, 1.0, 10.0)  # λ grid; 10 ≈ the identity (the plain embedder)


def choose_lambda(q: np.ndarray, c: np.ndarray, pos: list[list[int]], folds: int = 3,
                  steps: int | None = None, margin: float = 0.02) -> tuple[float, dict[str, float], bool]:
    """3-fold cross-validation inside the training questions (the holdout is never touched). A λ is only
    chosen over the plain embedder if its adapter beats it on the left-out folds by more than `margin`
    mean MRR *and* in at least folds − 1 of them — with a few dozen questions a small edge is often luck.
    Otherwise the largest λ (≈ the identity) wins, so by default an adapter does no harm.
    -> (λ, mean left-out MRR per λ and for the plain embedder, whether any λ passed)."""
    n = len(q)
    if n < 2 * folds:
        return LAMBDAS[-1], {}, False
    idx = np.arange(n)
    parts = [idx[f::folds] for f in range(folds)]
    plain = [rank_metrics(q[p], c, [pos[i] for i in p])["mrr"] for p in parts]
    scores: dict[str, float] = {"identity": round(float(np.mean(plain)), 4)}
    best, best_gain, passed = LAMBDAS[-1], 0.0, False
    for lam in sorted(LAMBDAS, reverse=True):
        mrr = []
        for f, held in enumerate(parts):
            tr = np.concatenate([p for g, p in enumerate(parts) if g != f])
            w = fit(q[tr], c, [pos[i] for i in tr], lam=lam, **({"steps": steps} if steps else {}))
            mrr.append(rank_metrics(q[held], c, [pos[i] for i in held], w)["mrr"])
        scores[str(lam)] = round(float(np.mean(mrr)), 4)
        gain = float(np.mean(mrr) - np.mean(plain))
        if gain > margin and sum(m > p for m, p in zip(mrr, plain)) >= folds - 1 and gain > best_gain:
            best, best_gain, passed = lam, gain, True
    return best, scores, passed


def split(item_ids: list[str]) -> list[bool]:
    """Deterministic holdout membership (~25%), by a hash of the item id."""
    return [int(hashlib.sha256(i.encode()).hexdigest(), 16) % 100 < HOLDOUT * 100 for i in item_ids]


async def training_data(project_id: str, cfg: dict[str, Any], set_id: str, job: Job
                        ) -> tuple[np.ndarray, np.ndarray, list[list[int]], list[str], dict[str, Any], str]:
    """-> (question vectors, chunk vectors, positives per question, item ids, build, embed_key)."""
    from . import retrieval

    build = await evaluate.ready_build(project_id, cfg, job)
    embedder = build_node("embed", cfg["embed"])
    rows = await db.fetch_all("SELECT id, document_id, text, text_sha FROM chunks WHERE build_id=? ORDER BY id",
                              (build["id"],))
    vecs = await retrieval.chunk_vectors({r["id"]: r for r in rows}, embedder.embed_key())
    chunks = [r for r in rows if r["id"] in vecs]
    c = np.stack([vecs[r["id"]] for r in chunks]) if chunks else np.zeros((0, 1), np.float32)
    items, q, pos = [], [], []
    job.progress("embed", 0, 1)
    for it in await evaluate.valid_items(set_id):
        p = [j for j, ch in enumerate(chunks) if M.is_hit(ch, it)]
        if p:  # a question whose evidence no chunk holds can't teach anything
            items.append(it["id"])
            pos.append(p)
            q.append(await embedder.embed_query(it["question"]))
    job.progress("embed", 1, 1)
    return (np.stack(q) if q else np.zeros((0, c.shape[1]), np.float32)), c, pos, items, build, embedder.embed_key()


async def train(job: Job, adapter_id: str, project_id: str, version: dict[str, Any], set_id: str) -> dict[str, Any]:
    try:
        return await _train(job, adapter_id, project_id, version, set_id)
    except Exception as e:
        async with db.tx() as c:
            await c.execute("UPDATE adapters SET status='failed', error=? WHERE id=?", (vault.redact(str(e)), adapter_id))
        raise


async def _train(job: Job, adapter_id: str, project_id: str, version: dict[str, Any], set_id: str) -> dict[str, Any]:
    import asyncio

    cfg = with_defaults(db.loads(version["config"], {}))
    q, c, pos, items, build, embed_key = await training_data(project_id, cfg, set_id, job)
    if len(items) < MIN_QUESTIONS:
        raise evaluate.EvalError(f"An adapter needs at least {MIN_QUESTIONS} eval questions whose evidence is in the "
                                 f"index; this set has {len(items)}. Generate a larger set.")
    hold = split(items)
    tr = [i for i, h in enumerate(hold) if not h]
    ho = [i for i, h in enumerate(hold) if h]
    if not ho:  # tiny or unlucky split: hold out the last question
        tr, ho = tr[:-1], tr[-1:]
    job.progress("train", 0, 3)
    lam, cv, cv_passed = await asyncio.to_thread(choose_lambda, q[tr], c, [pos[i] for i in tr])
    job.progress("train", 1, 3)
    w_tr = await asyncio.to_thread(fit, q[tr], c, [pos[i] for i in tr], lam=lam)
    holdout = {"before": rank_metrics(q[ho], c, [pos[i] for i in ho]),
               "after": rank_metrics(q[ho], c, [pos[i] for i in ho], w_tr)}
    job.progress("train", 2, 3)
    w = await asyncio.to_thread(fit, q, c, pos, lam=lam)
    full = {"before": rank_metrics(q, c, pos), "after": rank_metrics(q, c, pos, w)}
    job.progress("train", 3, 3)
    path = adapter_path(project_id, adapter_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, w)
    metrics = {"questions": len(items), "train": len(tr), "holdout": holdout, "full": full,
               "chunks": int(len(c)), "dim": int(c.shape[1]),
               "generalises": holdout["after"]["mrr"] > holdout["before"]["mrr"],
               # Use it only if it beat the plain embedder in cross-validation AND on the unseen holdout.
               "cv_passed": cv_passed,
               "recommended": cv_passed and holdout["after"]["mrr"] > holdout["before"]["mrr"],
               "params": {"tau": TAU, "lambda": lam, "steps": STEPS, "lr": LR},
               "cv": cv}  # mean held-out-fold MRR per λ (and for the plain embedder)
    async with db.tx() as tx:
        await tx.execute("UPDATE adapters SET status='ready', metrics=?, embed_key=?, build_id=?, dim=? WHERE id=?",
                         (db.dumps(metrics), embed_key, build["id"], int(c.shape[1]), adapter_id))
    return {"adapter_id": adapter_id, "holdout_mrr": holdout["after"]["mrr"]}
