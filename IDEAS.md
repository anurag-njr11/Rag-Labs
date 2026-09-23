# RAG Builder — Idea Catalogue

> Working notes from the planning sessions. Every idea we surfaced, why it matters,
> what it costs, and where it lands. Includes the ideas we rejected and why — those
> are often more useful than the ones we kept.
>
> Last updated: 2026-09-23

---

## 0. How to read this

Each idea carries four tags:

- **Value** — how much it moves the product (`low` / `medium` / `high` / `core`)
- **Cost** — rough build effort
- **Phase** — where it lands in the 3-phase plan
- **Source** — where the idea came from

The single organising insight behind almost everything below:

> **Building a RAG pipeline is a solved, commoditised problem.
> Knowing whether it is any good — and knowing that the corpus underneath it is any good —
> is not.**

Every idea that survived was kept because it serves that sentence. Every idea that was
cut, was cut because it didn't.

---

## 1. Core thesis ideas

### 1.1 Measurement, not construction, is the product
**Value: core · Cost: — · Phase: 2 · Source: positioning discussion**

Five GUI RAG builders already exist (LangFlow, Flowise, RAGFlow, Dify, n8n-style tools).
Competing on "drag nodes to build a pipeline" is competing on polish against funded teams.

Reframe: *"Upload your docs. We generate an eval set, sweep N configurations against it,
and hand you the winning pipeline."* The builder becomes the on-ramp; the **Lab** is the product.

### 1.2 The corpus is the bigger lever than the config
**Value: core · Cost: — · Phase: 2–3 · Source: Infosys whitepaper + general analysis**

Chunk size might move quality 10%. A missing document caps it at zero forever.
Infosys, reporting from a real deployment:

> *"In about 70% of these cases, the perceived error could be attributed to outdated or
> incorrect documentation that requires updating."*

And the widely repeated (vendor-sourced, so discount the precision) figure that
**~80% of RAG failures originate in the ingestion/chunking layer, not the LLM.**

Both point the same way: aim the product upstream. Optimise the *knowledge base*,
not just the retriever.

### 1.3 Each phase ships a complete, usable product
**Value: core · Cost: — · Phase: all · Source: user constraint**

Not MVP → nice-to-haves. Three releases, each standalone:
Phase 1 = a working RAG chatbot. Phase 2 = it tells you whether it's good.
Phase 3 = it keeps telling you, from real traffic, and handles advanced retrieval.

---

## 2. The Lab — measurement engine

### 2.1 Auto-generated eval sets (zero labelling)
**Value: core · Cost: ~1 day · Phase: 2 · Source: original plan**

Sample chunks → ask an LLM to generate a question answerable *only* from that chunk +
a gold answer → **validity filter**: try to answer with no context; if the model gets it
right, the question is too generic, discard it. Output: 50–100
`(question, gold_answer, gold_chunk_id)` triples in ~2 minutes.

This single feature unlocks everything downstream: sweeps, diagnostics, embedding
adapters, DSPy, regression guards. It is the keystone.

### 2.2 Config sweep with a content-addressed cache
**Value: core · Cost: ~2 days · Phase: 2 · Source: original plan**

Cartesian grid over the pipeline axes, budget-capped, parallel.

**The critical engineering detail:** key every artifact by the hash of the config that
produced it — `chunks[hash(parse+chunk cfg)]`, `vectors[hash(chunks+embed cfg)]`.
A naive 72-cell sweep re-embeds the corpus 72 times and dies on stage. With the cache
it costs ~6 embedding passes. Retrofitting this later means touching every node.

### 2.3 Pareto leaderboard (quality vs. cost)
**Value: high · Cost: ~1 day · Phase: 2 · Source: original plan**

Sortable table plus a scatter plot with the Pareto frontier drawn. Click a point →
**Promote to production**. Plus a plain-English insight line:
*"Reranking added 14% faithfulness for +180ms and +$0.4/1k queries."*
That sentence is what people repeat back to each other.

### 2.4 Auto-Optimize (successive halving)
**Value: high · Cost: ~150 lines · Phase: 2 · Source: original plan**

Score all candidates on cheap deterministic retrieval metrics, promote the top ~25% to
expensive LLM-judge evaluation. Frame as "AutoML for RAG". Large perceived sophistication
for very little code.

### 2.5 The 7-mode failure taxonomy, deterministically classified
**Value: core · Cost: ~1.5 days · Phase: 2 · Source: Infosys whitepaper ⭐**

The best single find of the research. Infosys's failure taxonomy is sharper than the
4-category scheme we had — and because the eval set carries `gold_chunk_id`, **most modes
are detectable with arithmetic and set operations, no LLM judge involved.**

| Failure mode | Deterministic detection | Prescribed fix |
|---|---|---|
| Lack of content | Gold chunk exists nowhere / nothing clears a similarity floor | **Corpus gap** → content backlog |
| Overlooked top-ranked doc | Gold chunk ranks at position *n > k* | Raise `top_k` / add reranker |
| Consolidation loss | Gold chunk in top-k but absent from final context | Fix truncation/packing budget |
| Failure to extract | Gold chunk *is* in context, answer still wrong | Prompt / model / context noise |
| Incorrect format | Structured-output validation fails | Format constraint |
| Inappropriate specificity | Length + detail heuristic vs. gold | Prompt tuning |
| Incomplete answer | Count gold-answer facets present in response | Query decomposition |

Consequence: **diagnostics are fully reproducible even though judge scores are not.**
Ship diagnostics as the deterministic layer, judge scores as the noisy layer on top.

### 2.6 Regression guard ("CI for RAG")
**Value: medium · Cost: ~0.5 day · Phase: 2 · Source: original plan**

Every pipeline edit re-runs the eval set and shows a diff vs. the promoted version:
*"faithfulness 0.81 → 0.87 ▲, latency 240ms → 410ms ▼."*

### 2.7 Cost simulator
**Value: medium · Cost: ~2 hours · Phase: 2 · Source: original plan**

"At 10k queries/month, config A costs $X, config B costs $Y." One formula,
disproportionate credibility with anyone who has paid an inference bill.

---

## 3. Corpus health — the pivot

### 3.1 Coverage gap detection → content backlog
**Value: core · Cost: ~1 day on top of the Lab · Phase: 2 · Source: pivot discussion ⭐**

A *"lack of content"* failure **is** a coverage gap. Same machinery, different label —
and a different buyer. Output: *"Your documentation cannot answer 23% of what users
actually ask. Here are the twelve missing topics, ranked by query volume."*

Why this is the business: the buyer moves from an ML engineer doing a one-week tuning
task to a docs/support/knowledge-ops owner with a recurring problem and a budget, and the
value attaches to a business metric (ticket deflection) rather than to nDCG.

### 3.2 Contradiction and staleness detection
**Value: high · Cost: ~1 day · Phase: 2 · Source: pivot discussion**

Scan embedding neighbourhoods for near-duplicate chunks, then run an LLM contradiction
check on the pairs. Surface: *"Doc A says X, Doc B says not-X; retrieval picks one at random."*
Plus stale detection via `stale_after` / last-modified.

### 3.3 Dead weight detection
**Value: medium · Cost: ~2 hours · Phase: 2 · Source: pivot discussion**

Chunks that are never retrieved by any eval question or production query. Content nobody
needs, inflating the index and diluting retrieval.

### 3.4 Production query ingestion (closes the loop)
**Value: high · Cost: ~1 day · Phase: 3 · Source: pivot discussion**

Feed real user queries back into gap detection so the analysis runs on what people
actually ask, not only on synthetic questions. This is what turns a one-shot audit into
a living system — and into a subscription.

---

## 4. Sweep axes (the knobs worth measuring)

### 4.1 Sweep the *parser*, not just the chunker
**Value: high · Cost: ~0.5 day · Phase: 2 · Source: derived from the "80% ingestion" claim ⭐**

`parser ∈ {pymupdf, pdfplumber, unstructured, docling, ocr}`

If most failures originate upstream of chunking, the grid was starting at the wrong layer.
Different extractors mangle tables, columns and headers in entirely different ways, and
which one wins is corpus-dependent — exactly the condition where a sweep is the answer.
**No competing tool sweeps the parser.** Also upgrades the Phase 1 parse-quality indicator
from a vibe into a measured number.

### 4.2 Chunking strategies
**Value: high · Cost: ~0.5 day each · Phase: 1–2 · Source: Infosys + arXiv**

- Fixed / recursive (Phase 1 baseline)
- **Structure-aware** (Markdown heading-aware) — nearly free, often wins on technical docs
- **Semantic chunking** — reported as effectively mandatory for financial/compliance/technical corpora
- **Atomic table chunks** — detect tables, extract as Markdown/CSV, never split them. An afternoon's work and a real correctness fix, not a feature.

### 4.3 Retrieval strategies
**Value: high · Cost: ~0.5 day each · Phase: 2–3 · Source: Infosys**

- Dense / hybrid / hybrid+rerank (baseline)
- **Sentence-window retrieval** — retrieve target sentence, expand to a surrounding window
- **Auto-merging retrieval** — merge adjacent retrieved chunks
- **Multi-query retrieval** — generate N query variants, take the union
- **HyDE** — embed a hypothetical *answer* document rather than the question
- **Query expansion**
- **Query decomposition** — split multi-hop questions, retrieve per sub-question, merge

Sentence-window and auto-merging directly attack the chunk-boundary-split failure, giving
that diagnostic a prescribed fix beyond "increase overlap".

### 4.4 Semantic caching
**Value: medium · Cost: ~0.5 day · Phase: 2 · Source: Infosys**

Standard caching can't tell *"top 10 best practices"* from *"top 15 best practices"*.
Semantic caching (e.g. GPTCache) keys on meaning, returns a hit above ~95% similarity.
Two uses: a cost/latency axis in the product, and an accelerator inside the sweep runner.

### 4.5 Embedder selection, MTEB-seeded
**Value: medium · Cost: ~2 hours · Phase: 2 · Source: Infosys**

Seed Auto-Optimize with MTEB-ranked candidates rather than an arbitrary list, so the
search starts from good candidates. Selection criteria worth exposing in the UI:
retrieval average (NDCG@K), model size, max tokens, embedding dimensions.

Infosys's own caveat is the product's thesis, stated by someone else:

> *"These benchmarks are self-reported... some models might have been trained on the MTEB
> datasets... it is advisable to assess the models on your own dataset before making a
> final decision."*

They name the need and ship no tool for it. That is the gap.

### 4.6 Agentic retrieval as a measured axis
**Value: high · Cost: ~3 hours on top of the sweep runner · Phase: 3 · Source: LangChain deepagents docs ⭐**

Plan → search → read → synthesize loop, as one option in the `retrieve` slot:
`retriever ∈ {dense, hybrid, hybrid+rerank, agentic}`.

The point is not to build an agent. The point is that the leaderboard then answers a
question the whole industry is currently arguing about:
*does agentic RAG actually beat hybrid+rerank, and at what cost multiple?*
e.g. *"agentic: +9% faithfulness, 4.1× cost, 6× latency — worth it for legal, not for support chat."*

**Do not make the whole product agentic.** A demo where every query takes 20s dies on stage.

### 4.7 Context offloading
**Value: medium · Cost: ~1 hour · Phase: 3 · Source: LangChain deepagents docs**

The retrieval tool writes chunks to a store and returns *references*, not text, keeping the
orchestrator's context small; sub-agents read individual files. A real token-cost lever,
measurable on an axis already tracked. Only meaningful on the agentic path.

---

## 5. Learning from the eval set (the compounding ideas)

These two are the strongest "unfair advantage" ideas, and they exist *only* because
the eval generator produces labelled data for free.

### 5.1 Domain embedding adapter trained on the generated eval set
**Value: high · Cost: ~1 day · Phase: 3 · Source: Infosys (technique) + our eval generator (data) ⭐**

Domain embedding adaptation normally needs labelled `(query, relevant passage)` pairs,
which nobody has — which is why almost nobody does it.
**Our eval generator produces exactly those pairs.**

Train a small linear projection over frozen embeddings with a contrastive loss.
A few hundred lines, CPU-trainable for a small adapter, no new data pipeline.

> *"We fine-tuned an embedding adapter on your corpus using the eval set we generated.
> Recall@5: 0.71 → 0.84. You labelled nothing."*

Also makes the product stickier — an adapter is a per-corpus artifact, not a config file.

### 5.2 DSPy prompt optimisation against the generated eval set
**Value: high · Cost: ~1 day · Phase: 3 · Source: Infosys ⭐**

DSPy (Stanford NLP) converts prompt engineering from artisanal tinkering into a training
loop, optimising instructions and few-shot examples against a metric on a labelled set —
again, the set we generate. Reported gains on multi-hop RAG are large.

Pairs with 5.1 for a single Phase 3 headline:
*"We optimised your prompt **and** your embeddings against an eval set you didn't write."*

### 5.3 The config prior (the moat)
**Value: high (long-term) · Cost: instrumentation now, model later · Phase: 2 instrument / 3+ use · Source: business discussion ⭐**

Every sweep produces a labelled data point: *corpus fingerprint*
(doc types, average length, structure density, domain, language) → *winning config* → *score*.

Accumulate enough and you can **predict the best config without running the sweep**:

> *"Corpora like yours — dense technical PDFs with tables — win with semantic chunking at
> ~800 tokens, hybrid retrieval, reranking on. Confidence 0.81 from 340 similar corpora.
> Verify with a 90-second sweep?"*

Not copyable with code — it requires the sweep data, which requires having been first.
Converts the slowest feature into an instant answer. **Instrument for it from Phase 2**
(log fingerprint + winning config, anonymised) even though it's useless until there's volume.

---

## 6. Determinism and exactness

### 6.1 Deterministic lookup path alongside semantic retrieval
**Value: high · Cost: ~1 day · Phase: 1 · Source: user's second project idea ⭐**

Embeddings are genuinely *bad* at exact identifiers — `AttributeError: 'NoneType' object
has no attribute 'get'`, `ECONNREFUSED`, `torch.nn.functional.scaled_dot_product_attention`.
Cosine similarity smears these into near-neighbours that are subtly wrong.

Route exact strings to exact lookup: **SQLite FTS5 + an exact-match table** keyed on a
*normalised* signature (strip memory addresses, file paths, line numbers, quoted values) so
`...has no attribute 'get'` and `...has no attribute 'items'` collapse to one template.
The normalisation step is most of the value.

New sweep axis: `lookup ∈ {semantic, exact, fused}`.

### 6.2 Fuse both paths instead of routing with a classifier
**Value: high · Cost: negative (removes code) · Phase: 1 · Source: critique of the router design ⭐**

An LLM classifier deciding "semantic or exact?" adds a call of latency and a silent
failure mode when it misroutes. Deterministic lookup costs under a millisecond, so:
**always run both and fuse with Reciprocal Rank Fusion.** If exact hits, it dominates the
fused ranking naturally; if it misses, it contributes nothing. Same behaviour, no classifier,
one less LLM call, no misroute.

### 6.3 What is actually non-deterministic in the pipeline
**Value: high · Cost: — · Phase: 1–2 · Source: determinism analysis**

| Source | Deterministic? | How to pin |
|---|---|---|
| Chunking | Yes, if the splitter is pure | Keep LLM out of the chunker, or cache by config hash |
| Embedding | Yes on CPU with a pinned model | Pin model **and** version; GPU float reductions can differ |
| Vector search | **Brute-force cosine: yes.** HNSW/IVF: **no** | Phase 1's numpy brute force is fully deterministic — a quiet advantage |
| Tie-breaking | Often not | Sort by `(-score, chunk_id)`; never trust library ordering |
| Reranker | Yes, same rules as embedding | Pin version |
| LLM judge | **No — and not fully fixable** | See below |

On current Claude models (Opus 5, Sonnet 5, the 4.6+ family) `temperature`/`top_p`/`top_k`
were removed and return a 400 — **you cannot set `temperature=0` on the judge.** Mitigations:

- Lead the leaderboard with the **deterministic retrieval metrics** (hit-rate@k, MRR, nDCG)
- Make judge scores **discrete ordinals** via structured outputs, not free floats
- Run the judge 3× and take the **median** near decision boundaries
- Report **confidence intervals**; mark overlapping configs as tied rather than ranked
- `claude-haiku-4-5` still accepts sampling params — variance reduction, not a guarantee

### 6.4 OKF (Open Knowledge Format) — Google Cloud, June 2026, v0.2
**Value: high · Cost: ~1 day import / ~1 day export · Phase: 2 metadata, 3 full · Source: user suggestion + spec**

A packaging convention for curated knowledge: a directory tree of Markdown with YAML
frontmatter. `type` is the only required key; consumers **must not** reject bundles for
missing fields, unknown types or broken links.

It is **not** a retrieval mechanism and does not make semantic queries deterministic.
Determinism lives in exactly one place: the **Attested Computation** type (6.5).

The real value for us is that its frontmatter is *already* the Corpus Health schema:

| Our corpus-health signal | OKF field |
|---|---|
| Stale documents | `stale_after`, `status: deprecated` |
| Untrusted content | `verified` + derived trust tiers (`human:` / `process:` / agent) |
| Citation provenance | `sources[]` with per-claim footnotes |
| Dead weight | `usage_count`, `usage_window` |

Two moves: **ingest** OKF bundles (get staleness/trust/provenance for free, and use them in
retrieval — down-rank `deprecated`, filter past `stale_after`), and **emit** OKF as the
output of Corpus Health. The second is the wedge: *"point us at your messy docs, get back a
conformant knowledge base with provenance, trust tiers and staleness attached."*

Caution: v0.2, three months old, unproven adoption. Interoperability target, not a foundation.
Most published commentary overstates it as a "RAG replacement" — read the spec, not the takes.

### 6.5 Attested Computation for numeric facts
**Value: medium · Cost: ~1 day · Phase: 3 · Source: OKF spec**

For computed values ("Q3 revenue", "active users in region X"), don't retrieve a number out
of a document — run a **sanctioned computation** and verify the receipt:

```yaml
type: Attested Computation
runtime: bigquery
parameters: [{name: year, type: integer, required: true}]
computation: references/computations/revenue.sql
executor: {resource: ..., receipt: [job_id, executed_sql, result]}
attester:  {resource: references/attesters/revenue.py}   # deterministic, no-LLM
```

Flow: discover → load contract → parameterise → execute → attest → gate display.
The agent supplies parameter *values* only; it cannot author the computation.
Kills a whole class of failure — the confidently-wrong figure pulled from a stale slide.

Clean architectural line: **numbers come from attested computations, prose comes from retrieval.**

### 6.6 Text-to-SQL for tabular sources, executed read-only
**Value: medium · Cost: ~1 day · Phase: 3 · Source: Infosys**

For CSV/XLS/database sources, generate SQL from natural language. Infosys's practical note:
have the LLM *generate* the query and execute it yourself with **read-only access**, rather
than handing the model database credentials.

---

## 7. Trust, safety, verification

### 7.1 Prompt-injection resistance testing
**Value: high · Cost: ~3 hours · Phase: 3 · Source: LangChain deepagents docs + our extension ⭐**

The deepagents docs flag indirect prompt injection through retrieved content and then admit
*"no strategy provides reliable protection."* An open problem stated in vendor docs is a
perfect thing for a measurement tool to measure.

Inject canary documents carrying payloads (instruction override, exfiltration attempts,
fake-citation instructions), run the eval set, report an **Injection Resistance score per
config**, and show which defences actually move it (source prefixing, data-treatment framing,
the grounding-check node, output validation).

Why it wins: every hackathon has RAG projects, approximately none have a security story.
It reuses the eval harness. And it is dramatic live:
*"watch me hijack this chatbot through a PDF — now watch this config block it."*

### 7.2 Grounding check as a runtime node
**Value: high · Cost: ~2 hours · Phase: 3 · Source: LangChain deepagents docs**

Not just an offline metric — a verifier **in the request path** that grades the answer against
retrieved context before returning, with one retry on failure:

```json
"verify": {"type": "grounding_check", "on_fail": "retry_with_more_context", "max_retries": 1}
```

Gives a clean Lab comparison (on vs. off: faithfulness up, p95 latency up) and feeds diagnostics.

### 7.3 Validation loop with sandboxed execution (code vertical)
**Value: core (for the code vertical) · Cost: ~3 days · Phase: 3 · Source: user's second project idea ⭐**

Generate code → run it in a sandbox → run tests → self-correct. **This produces ground truth
for free.** Code is one of very few domains where "is this answer correct?" is machine-checkable
rather than a judgment call.

Governors that keep it from dying:
- Prefer the library's **own test suite** → doctests in retrieved docs → generated tests last
  (generated tests are as likely to be wrong as the code; when both are wrong the loop converges
  on confident nonsense)
- Hard step cap (3–4) and a no-progress detector (same failing test twice → stop)
- Honest escape hatch: return the best attempt marked *"couldn't verify"* rather than looping
- Real isolation: container, no network, memory cap, timeout — the one place the "no Docker"
  rule should bend

### 7.4 Guardrails and safety metrics
**Value: low-medium · Cost: varies · Phase: 3 · Source: Infosys**

NeMo Guardrails (programmable rails, Colang) for input/output control. Toxicity and bias as
evaluation dimensions alongside faithfulness. Relevant only if chasing enterprise.

### 7.5 Citation-support checking
**Value: medium · Cost: ~0.5 day · Phase: 3 · Source: problem-space survey**

Citations that look right but don't actually support the claim. Check each cited span
against the claim it's attached to.

---

## 8. Product surfaces

### 8.1 Retrieval inspector
**Value: high · Cost: ~1 day · Phase: 1 · Source: original plan**

Per answer: retrieved chunks with scores, source page highlighted in the PDF viewer,
per-claim citations, tokens + cost + latency. Judges and users test with a trick question;
being able to *show why* converts a bad answer into a credibility win.

### 8.2 Trace view
**Value: high (mandatory for Phase 3) · Cost: ~1 day · Phase: 3 · Source: agentic discussion**

Step-by-step timeline — query → each search → offload → each sub-agent → verification → answer
— with tokens/latency/cost per step. Single-shot RAG is legible from the inspector alone;
an agentic run is not. Without this, agentic configs are a black box on stage, defeating the point.

Cheap **if** the node contract emits trace events from Phase 1 (see 10.1).

### 8.3 Export to a real repo
**Value: high · Cost: ~0.5 day · Phase: 2 · Source: original plan**

Jinja-template the pipeline JSON into a working project (`app/`, `requirements.txt`,
Dockerfile, compose, README) and zip it. Kills the "it's just a toy" objection, and if the
goal is "help people ship better RAG", the deliverable is a config and a repo they own —
not a chatbot they rent.

### 8.4 Chat-to-build
**Value: medium · Cost: ~1 hour · Phase: 3 · Source: original plan**

*"Add a reranker and switch to hybrid"* → LLM emits a schema-valid JSON patch (structured
outputs) → the canvas animates the change. Cheap because the pipeline is already JSON.

### 8.5 Node canvas
**Value: low-medium · Cost: ~3 hours read-only / ~2 days full · Phase: 1 read-only, 3 full**

Phase 1: read-only graph as *navigation* — click a node, edit it in a side panel.
Functionally identical to a form, so it is the first thing to cut under time pressure.
Full drag-and-drop editing and branching in Phase 3.

**It is the prettiest feature and the least important one.** Build the Lab first.

### 8.6 Recipe gallery
**Value: low · Cost: ~1 day · Phase: 3 · Source: original plan**

Share a pipeline config by URL; fork someone else's. Also quietly feeds the config prior (5.3).

---

## 9. Business and positioning

### 9.1 The three candidate identities
**Source: positioning discussion**

| Identity | Core screen | Verdict |
|---|---|---|
| Learn RAG | Canvas with explanations | ❌ Served by a hundred free tutorials |
| NotebookLM clone | Chat | ❌ Google already won it, and it's free |
| **RAG optimizer / corpus health** | **Leaderboard** | ✅ Real unserved user, tractable for a solo build |

The other two come free as byproducts: running a sweep teaches more RAG than any tutorial,
and the NotebookLM-like experience *is* Phase 1's playground. They just aren't the point.

### 9.2 Headline metric: time to first evidence
**Value: high · Source: positioning discussion**

Corpus uploaded → leaderboard with a Pareto frontier, **under five minutes, zero labelled data.**
That number is the product. Optimise it.

### 9.3 Pitch lines worth keeping

- *"Stop guessing your RAG config. Measure it."*
- *"Your RAG isn't bad because of chunk size. It's bad because your docs don't answer the question. We show you which ones."*
- *"RAG Builder is the place you find out your RAG config is wrong — and which one to use instead."*
- Phase stack: *"Phase 1 gives you a working RAG chatbot. Phase 2 tells you whether it's any good and makes it better. Phase 3 keeps telling you, from real questions, forever."*

### 9.4 The code vertical as the proving ground
**Value: high · Source: synthesis of both project ideas ⭐**

The two project ideas overlap ~70% (parse, chunk, index, hybrid retrieve, rerank, evaluate).
Building both means building that stack twice. The synthesis:

> **RAG Builder, with code/technical documentation as the first vertical, where correctness is
> verified by execution.**

It fixes the weakest joint in each:
- The Lab's quality metrics depend on a non-deterministic LLM judge → execution gives hard,
  reproducible ground truth
- A local Qwen coding agent competes with Cursor/Copilot/Claude Code and loses → reframed, its
  differentiator is that the retrieval layer underneath is *measured*, and answers are *verified*

Demo that lands: *"Here's a stack trace. Watch it retrieve, answer, run the code, fail,
self-correct, and pass."*

---

## 10. Engineering lessons (mostly from the Infosys deployment report)

### 10.1 The node contract must carry trace events from day one
**Value: core · Cost: one extra line per node · Phase: 1 ⭐**

```python
class Node:
    def run(self, ctx: RunContext, inp): ...
    # inside: ctx.emit("search", query=q, tokens=n, ms=t)
```

Phase 1 nodes emit once and return. Phase 3's agentic retriever emits forty times and still
returns. Same signature, no rewrite — and the Phase 3 trace view becomes a rendering of events
already being collected.

(An earlier design used async generators; the `ctx.emit` callback is simpler and protects
Phase 3 just as well.)

### 10.2 Async or the sweep serialises
**Value: high · Cost: — · Phase: 1 · Source: Infosys ⭐**

Infosys hit blocking LLM calls in LangChain: at 50 concurrent users, average response went to
**180 seconds**, requests processed sequentially. After switching to async invocation: **~9 seconds.**

The sweep runner has the identical failure shape. Make node execution async in Phase 1 or
Phase 2's sweeps will crawl and you'll misdiagnose it as "sweeps are just slow".

### 10.3 Per-invocation cost accounting catches real bugs
**Value: high · Cost: — · Phase: 1 · Source: Infosys**

Their cost module revealed `ConversationalRetrievalChain` was silently making **two** LLM calls
per question (it rephrases first) — double billing and double latency, invisible in the code.

Takeaways: the `Run` record with per-step cost is load-bearing, not nice-to-have; and this is
another argument against building on LangChain.

### 10.4 Store raw files, always
**Value: high · Cost: trivial · Phase: 1 · Source: Infosys**

Needed to re-ingest whenever chunking changes — which is *every sweep cell*. Also needed for
deletion/GDPR, and for the "your source document is wrong" workflow. Cheap now, painful later.

### 10.5 Configuration as Code
**Value: high · Cost: — · Phase: 1 · Source: Infosys**

Validates pipeline-as-JSON under version control. Their extra wrinkles for later:
air-gapped targets can't reach Hugging Face, so cache models in object storage and pull at
bootstrap; keep images under 10 GB.

### 10.6 Provider abstraction layer
**Value: high · Cost: ~0.5 day · Phase: 1 · Source: Infosys**

Wrap model providers behind one spec so hosted → local swaps don't break anything.
Supports starting on a hosted model and moving in-house later — and supports the
local-Qwen/Ollama idea.

### 10.7 Vector store: use what you already have
**Value: high · Cost: — · Phase: 1–2 · Source: Infosys**

> *"Before choosing a separate vector database, consider the vector search features of the
> databases you currently use... your design can become simpler and operational complexity lowered."*

~~SQLite + numpy now → pgvector when it hurts → never a dedicated vector DB.~~

**Superseded (2026-09-23):** the vector database is now a *user choice* in Phase 1, because
comparing stores is part of the product. Five embedded stores ship — NumPy (exact), FAISS,
Chroma, Qdrant local mode, LanceDB — with no server or Docker. The Infosys point still holds in
a different form: keyword and exact-match search stay in SQLite for every store, so switching
stores changes only dense search and comparisons stay fair.

### 10.8 Keep raw brute-force search as long as possible
**Value: medium · Phase: 1–2**

Brute-force cosine over a few thousand chunks is sub-millisecond **and fully deterministic**.
ANN indexes (HNSW/IVF) are neither. Deterministic scores make the leaderboard trustworthy,
so defer ANN until corpus size genuinely forces it (~50k+ chunks).

---

## 11. Rejected — and why

| Idea | Why not |
|---|---|
| **Adopt the `deepagents` framework** | Makes LangChain load-bearing, drags in their state/backend abstractions, undercuts the "export a repo you own" pitch. Implement the patterns directly — 50–150 lines each. |
| **Build on LangChain / LlamaIndex generally** | Infosys's own report documents hidden double-billing and blocking calls inside the framework. Framework complexity is a liability for a measurement tool. |
| **Make the whole product agentic** | 20-second queries kill demos. Agentic stays one option on one axis; the Lab proves when it's worth it. |
| **LLM classifier routing semantic vs. exact** | Adds latency and a silent misroute failure mode. Always run both, fuse with RRF. |
| **Permissions-aware retrieval** | Biggest problem in the space, but it's an enterprise-sales business. Wrong shape for a project starting small. |
| **Connectors / freshness plumbing** | Huge, but it's Glean's game — an integration treadmill, not a product. |
| **Multi-agent orchestration, fine-tuning, custom vector DB, user-authored Python nodes** | Each eats days and adds nothing to the pitch. |
| **Streamlit frontend** | Would ship in two days, then be thrown away entirely — the canvas, inspector and leaderboard all fight it. |
| **Docker/Postgres/Celery/auth in Phase 1** | Ceremony while you're the only user. Added when their triggers fire (see PRD). |
| **Building for "learning RAG" or as a NotebookLM clone** | Both markets already won; both outcomes arrive free as byproducts of the optimizer. |
| **Chasing a genuinely novel technology** | The corpus-health idea isn't new tech — it's a new *object of attention*, reachable from where we're standing. Most durable products are that. |

---

## 12. Honest caveats

- **Developer infra tooling monetises badly.** Eval tools especially — teams build them
  in-house because it's "just a script". The corpus-health framing is the escape hatch
  precisely because it sells to a non-engineering buyer with a business metric attached.
  Don't drift back toward pure eval.
- **The flywheel needs users before it's a moat.** Until then it's just a sweep tool.
  Instrument for it early; don't plan around it.
- **Phase 1 alone is a weak product** — a passable NotebookLM clone with no differentiator.
  That's fine and expected. **The project becomes interesting the day the first leaderboard
  renders.**
- **The "80%" and "70%" figures are practitioner/vendor claims**, not peer-reviewed results.
  Directionally useful, not citable as fact.
- **Small local models are weak at long multi-step tool loops** — the most likely thing to
  disappoint in the code vertical. Keep loops short, scope each step narrowly, keep a hosted
  fallback switch.

---

## 13. Sources

- LangChain — RAG with Deep Agents: <https://docs.langchain.com/oss/python/deepagents/rag>
- OKF specification: <https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md>
- Google Cloud — Open Knowledge Format: <https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing>
- Infosys Tech Compass — RAG Challenges & Solutions: <https://www.infosys.com/iki/techcompass/rag-challenges-solutions.html> (bot-walled; full text supplied manually)
- PremAI — Building Production RAG (2026): <https://www.premai.io/blog/building-production-rag-architecture-chunking-evaluation-monitoring-2026-guide/>
- FloTorch — The 2026 RAG Performance Landscape: <https://www.flotorch.ai/blogs/the-2026-rag-performance-landscape-what-every-enterprise-leader-needs-to-know>
- arXiv — Chunking Methods on RAG: effectiveness vs. computational cost: <https://arxiv.org/pdf/2606.00881>
- arXiv — Evaluating Chunking Strategies for RAG in Oil and Gas Enterprise Documents: <https://arxiv.org/pdf/2603.24556>
