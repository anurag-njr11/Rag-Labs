# RAGLabs — Follow-ups

Problems that were found, investigated as far as was worth it at the time, and parked because they
are not blocking. Each entry says what is known, the evidence, and where to start. Remove an entry
when it is fixed (and note the fix in `DEVELOPER_ARCHITECTURE.md`).

Last updated: 2026-10-06

---

## 1. `fused` still trails `hybrid` on code-heavy docs

**Status:** partly fixed · **Priority:** medium (affects the default retriever)

**What was fixed (2026-10-06):** the exact-match path counted incidental symbol mentions
(`model_dump`, `ValidationError`, …) as exact hits. They all tied, RRF turned the arbitrary
chunk-id tie order into a strong boost, and `fused` scored MRR **0.61** vs `hybrid` **0.96** on the
Pydantic Docs project — and the score changed between two identical builds, because chunk ids
are build-specific. `exact_search` now skips `symbol`-kind rows; question symbols still match
section *headings*. See `DEVELOPER_ARCHITECTURE.md` Part 16 → Exact matching.

**What's left:** on the same eval set (13 questions, active v3 config) `fused` is now **0.885**
(Hit@k 1.00) vs `hybrid` **0.962**. Per-question ranks:

```
fused  [1, 1, 2, 1, 1, 2, 2, 1, 1, 1, 1, 1, 1]
hybrid [1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1]
```

The three questions that drop to #2 (#3 "custom error message for the 'int_parsing' error type in the
example", #7 "what should validation code raise instead of ValidationError", plus one near-tie) look
like the **defining-section pin / heading match** winning over the passage that actually answers:
e.g. the `int_parsing` reference section is pinned above the custom-error-message example. That is the
`pin_definitions` trade-off working as designed — it's right for "What is int_parsing?" and wrong for
"what does the example do with int_parsing?".

The other three projects with eval sets (prose corpora) score identically under `fused` and `hybrid`.

**Where to start:**
- `backend/app/engine/retrieval.py` → `exact_search`, the `pin_definitions` block in `retrieve()`;
  `backend/app/ingest/lookup.py` → `KIND_WEIGHT`.
- Ideas to measure (with a sweep, not by eye): pin only when the question is short / mostly the
  identifier ("What is X?", "X"); lower `exact_weight` for heading matches in long questions.
- Don't change the recommended default (`fused`) until a sweep on more than one code corpus says so —
  13 questions is within noise for a 1-question difference.
- Repro scripts used: compare fused/hybrid per question on a build with `retrieval.retrieve(...)` and
  `evalmetrics.first_hit_rank(...)` for each `eval_items` row.

---

## 4. Frontend warnings

**Status:** open · **Priority:** low (dev-only / build-size)

- `oxlint`: 19 `react(only-export-components)` warnings across 10 files (all pre-existing):
  `features/playground/{chunkText,markdown,Sources,Inspector,Trace}.tsx`,
  `components/ui/{Tabs,CodeBlock,Card,Button}.tsx`, `app/JobProgress.tsx`. Each file exports helper
  functions/constants next to components, so Vite fast refresh falls back to a full page reload when
  it changes (dev-only; no runtime effect). Fix: move the helpers into sibling `*.utils.ts` files.
- `npm run build`: "Some chunks are larger than 500 kB after minification". Route components are
  already lazy-loaded; check which shared dependency (likely GSAP / markdown / icons) lands in the
  main chunk with `npx vite-bundle-visualizer`, then split it or raise `chunkSizeWarningLimit`.
