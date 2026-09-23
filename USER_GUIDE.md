# RAG Builder User Guide

**Phase 1 — Build & Chat:** Upload documents, tune every pipeline parameter, chat with cited answers, and inspect retrieval.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Core Concepts](#core-concepts)
3. [Step-by-Step Tutorial](#step-by-step-tutorial)
4. [Pipeline Configuration Guide](#pipeline-configuration-guide)
5. [Using the Playground](#using-the-playground)
6. [Debugging & Tuning Strategies](#debugging--tuning-strategies)
7. [API Reference](#api-reference)

---

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python fetched automatically)
- Node.js 20+
- A free LLM key (optional for retrieval; required for chat):
  - [Gemini API](https://aistudio.google.com/apikey) or
  - [NVIDIA](https://build.nvidia.com)

### Run Locally

```bash
# Copy and fill .env with your API keys
cp .env.example .env

# Terminal 1: Backend (http://127.0.0.1:8000)
cd backend
uv sync
uv run uvicorn app.main:app

# Terminal 2: Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

### Load the Demo

```bash
cd backend
uv run python scripts/seed_demo.py  # ~70 MB download on first run
```

Then open the Playground and try:
- *"How do I make a field optional with a default?"*
- Paste a raw error: `Input should be a valid integer, unable to parse string as an integer`

---

## Core Concepts

### The Pipeline

Every RAG system is defined by 8 **pipeline stages**:

| Stage | Purpose | Decides |
|---|---|---|
| **Parse** | Convert PDF/DOCX → Markdown | How much structure to extract; OCR or not |
| **Chunk** | Split text into chunks | Size, overlap, boundaries (heading-aware?) |
| **Embed** | Text → vectors | Model, normalization, prefixes |
| **Vector Store** | Store & search vectors | Index type (exact/approximate), speed vs. accuracy |
| **Retrieve** | Find relevant chunks | Dense/keyword/hybrid, weighting, top-k |
| **Rerank** | Re-score chunks | Cross-encoder (optional) |
| **Prompt** | Build LLM context | Context budget, instructions to LLM |
| **Generate** | LLM writes answer | Model, temperature, max tokens |

**Every parameter has an effect:**
- **⚡ Instant**: applied at query time (fast, no re-indexing)
- **🔁 Rebuild**: requires re-indexing documents (slow, cached when possible)

### Configuration Versions

Each pipeline is immutable. Editing creates a new version:
- Compare two versions with **Diff**
- Promote old versions with **Rollback** (creates a new copy)
- Never rewrite history

### Content-Addressed Caching

The system caches at every stage:
- Chunks are keyed by (parse config + chunk config + document hash)
- Vectors are keyed by (chunks + embedding config)

**Result**: Switching vector stores never re-embeds. Changing `top_k` doesn't rebuild.

---

## Step-by-Step Tutorial

### 1. Create a Project

1. On the home page, click **"+ New Project"**
2. Enter a name (e.g., "Python Docs") and optional description
3. Click **"Create"** → taken to the Create Wizard

### 2. Upload Documents (Documents Step)

**Option A: Upload Files**
- Drag PDFs/DOCX/MD/TXT/HTML onto the dropzone (or click to browse)
- Supported: `.pdf .docx .md .markdown .mdx .txt .rst .html .htm` (max 100 MB each)

**Option B: Ingest URLs**
- Click **"Add URL"**
- Paste the link
- Optionally enable **"Crawl sitemap"** (depth-limited) to fetch multiple pages
- Click **"Fetch"**

**After Upload:**
- You'll see a **Parse Quality Indicator** (✅ good, ⚠️ fair, ❌ poor)
- Shows: extracted char count, detected tables, OCR used?, empty pages
- Click **"Next"**

### 3. Configure the Pipeline (Configure Step)

For each stage card, click to expand and adjust parameters:

#### Parse
- **Type**: Choose `PyMuPDF4LLM` (Markdown tables), `PyMuPDF` (plain text + OCR), or `pypdf`
- Effect: **🔁 Rebuild** (different parsing = different chunks)

#### Chunk
- **Type**: `fixed` (simple), `recursive` (sentence-aware), or `structure_aware` (heading-aware)
- **Size**: 256–2048 (chars or tokens). Smaller = more specific; larger = more context per chunk.
- **Overlap**: 0–256. Prevents cutting mid-sentence.
- **Unit**: `chars` or `tokens`
- Effect: **🔁 Rebuild** (changes all chunks)

**Example**: For fine-grained Q&A, use `structure_aware` with size=512, overlap=100.

#### Embed
- **Type**: `fastembed` (local, free) or `gemini`/`nvidia` (API)
- **Model**: Different models have different dimensions and quality
  - `bge-small`: 384d, fast
  - `bge-base`: 768d, better quality
  - `MiniLM`: 384d, competitive
- **Normalize**: L2-normalize vectors (makes cosine = dot product)
- **Doc prefix / Query prefix**: Text prepended to chunks/questions (model-dependent)
- **Batch size**: How many docs to embed at once
- Effect: **🔁 Rebuild** (different embeddings), **⚡ Instant** (batch size, prefixes on API models)

**Example**: Start with `fastembed` + `bge-small` (downloads ~67 MB). If quality is poor, upgrade to `bge-base` or switch to Gemini.

#### Vector Store
- **Type**: 
  - `numpy` (exact, slow on large corpora)
  - `faiss` (fast, configurable exact/approximate)
  - `chroma` (batteries-included)
  - `qdrant` (graph-based, local mode)
  - `lancedb` (SQL + vectors)

- **For FAISS** (most common):
  - **Index Type**: `Flat` (exact), `IVFFlat` (clusters), or `HNSW` (graph)
  - **IVF parameters**: `nlist` (number of clusters)
  - **HNSW parameters**: `hnsw_m` (connections per node), `ef_construction` (build effort)
  - **Instant parameters**: `nprobe` (clusters searched), `ef_search` (search effort)

- Effect: **🔁 Rebuild** (type or structure params), **⚡ Instant** (search effort)

**Example**: Start with FAISS Flat (exact) for correctness. Switch to HNSW when you have >10k chunks and need speed.

#### Retrieve
- **Type**: `dense` (vectors only), `keyword` (BM25 only), `hybrid` (dense + BM25), or `fused` (dense + BM25 + exact-match, default)
- **top_k**: How many chunks to return (before reranking). Default 8; raise to 10–15 for more coverage.
- **Fusion**: `rrf` (rank-based) or `weighted` (score-based)
- **Weights**: `dense_weight`, `keyword_weight`, `exact_weight`. Boost paths you trust more.
- **Candidates per path**: How many each method contributes before fusion. Default 40; higher = slower but more options.
- **Min score**: Drop dense results below this similarity (0.0 = keep all)
- **MMR** (Maximal Marginal Relevance): Reorder results to avoid near-duplicates. `mmr_lambda=1.0` is pure relevance; 0.0 is pure diversity.
- **Pin defining sections**: Boost chunks whose heading exactly matches your question.
- Effect: **⚡ Instant** (all retrieval params are instant — no rebuild needed)

**Example**: For a code docs chatbot, use `fused` with `exact_weight=1.5` to boost error message matches. Enable `pin_definitions` to prioritize sections titled with the function you asked about.

#### Rerank
- **Type**: `none` (default) or `cross_encoder` (slower, more accurate)
- Effect: **⚡ Instant** (reranking doesn't rebuild)

**Example**: If retrieval is good but you get the right chunks in the wrong order, enable reranking.

#### Prompt
- **max_context_tokens**: How many tokens of retrieved chunks to include. Default 4000; lower to force conciseness; raise for detail.
- **say_dont_know**: Instruct the LLM to refuse unanswerable questions instead of hallucinating.
- **source_labels**: Include document names in the prompt (helps citations).
- Effect: **⚡ Instant** (affects only the prompt, not retrieval)

#### Generate
- **Model**: Pick from available models (empty = provider default)
- **Temperature**: 0.0–2.0. Lower = focused, repeatable; higher = varied.
- **Top-p**: Nucleus sampling. Lower = more focused.
- **Max tokens**: Hard cap on answer length.
- **Reasoning effort**: Extended thinking budget (`none`/`low`/`medium`/`high`)
- Effect: **⚡ Instant** (no rebuild)

**Example**: For customer-facing answers, use temperature=0.1 (deterministic). For creative tasks, use 0.7+.

### 4. Build the Index (Build Step)

1. Review the **Estimate** message (e.g., "will embed 1,240 chunks in FAISS, no re-embeddings")
2. Click **"Start Build"**
3. Watch live progress: Parse → Embed → Store → Keywords
4. On success, see stats: chunk count, time, cache hits
5. Click **"Go to Playground"**

---

## Pipeline Configuration Guide

### Quick Recipes

#### Best for Precision (Code/Technical Docs)
```
Chunk:     structure_aware, size=512, overlap=100
Embed:     bge-base (or fastembed)
Store:     faiss + hnsw
Retrieve:  fused (exact_weight=1.5), top_k=10, pin_definitions=true
Rerank:    off
Prompt:    max_context_tokens=4000, say_dont_know=true
Generate:  temperature=0.1, max_tokens=1024
```

#### Best for Speed
```
Chunk:     fixed, size=1024, overlap=0
Embed:     bge-small
Store:     numpy or faiss-flat
Retrieve:  hybrid, top_k=5, candidates=20
Rerank:    off
Prompt:    max_context_tokens=2000
Generate:  temperature=0.2, max_tokens=512, reasoning_effort=none
```

#### Best for Quality (Dialogue/General Knowledge)
```
Chunk:     recursive, size=768, overlap=150
Embed:     bge-base
Store:     lancedb + hnsw
Retrieve:  fused, top_k=8, mmr=true, mmr_lambda=0.7
Rerank:    on (cross-encoder)
Prompt:    max_context_tokens=4000, source_labels=true
Generate:  temperature=0.3, max_tokens=2048
```

### Parameter Effects

| If this is wrong | Symptom | Try |
|---|---|---|
| **Chunk size too large** | Missing details, answers feel generic | Reduce to 512 |
| **Chunk size too small** | Chunking boundaries cut context, answers disjointed | Increase to 1024 |
| **Embedding model weak** | Semantically unrelated chunks ranked high | Switch to bge-base or Gemini |
| **top_k too low** | Right answer not in top-5; "answer not in docs" | Raise to 10–15 |
| **top_k too high** | Slow queries, noisy context | Lower to 5–8 |
| **Temperature too high** | Hallucination, made-up facts | Lower to 0.1–0.2 |
| **Temperature too low** | Repetitive, overly cautious answers | Raise to 0.3–0.5 |
| **max_context_tokens too low** | Answer incomplete, chunks dropped | Raise to 4000–6000 |

---

## Using the Playground

### Ask a Question

1. Type a question in the chat box
2. Hit Enter or click **"Send"**
3. Watch the answer stream token-by-token
4. Citations appear as `[1]`, `[2]`, etc. in the text

### Inspect Retrieved Chunks (Left Panel)

**Each chunk shows:**
- **Chunk text**: The exact text sent to the LLM
- **Score**: 0.0–1.0 (higher = more relevant)
- **Retrieval path**: 🔍 Dense (vectors), 📖 Keyword (BM25), 🎯 Exact (symbol lookup)
- **Found by**: Which paths ranked it (e.g., "dense, keyword")
- **Document & page**: Where it came from
- **Heading**: Section breadcrumb (e.g., "API > Errors > Validation")
- **In context?** ✓ = made it into LLM prompt; ✗ = dropped due to token budget
- **Cited?** ✓ = answer cited this chunk with [n]

### Understand Why Answers Are Wrong

**Problem: Answer is vague or generic**
- **Look for:** Retrieved chunks don't contain specific detail
- **Diagnosis:** Are the right chunks in the top-10? If not, retrieval is failing.
- **Fix:** 
  - Increase `top_k` (e.g., 5 → 10)
  - Switch embedding model
  - Reduce chunk size (more specific splits)
  - Enable `pin_definitions` for code docs

**Problem: Right chunk retrieved but not used**
- **Look for:** Chunk is in the inspector with ✓ but says "In context: ✗"
- **Diagnosis:** Chunk was dropped due to token budget.
- **Fix:**
  - Increase `max_context_tokens`
  - Enable reranking to filter noise
  - Reduce chunk size (fewer tokens per chunk)

**Problem: Chunk in context but answer still wrong**
- **Look for:** All needed chunks are in context ✓; answer still bad
- **Diagnosis:** LLM synthesis failed, not retrieval.
- **Fix:**
  - Lower temperature (force focus)
  - Adjust prompt template (be more specific in instructions)
  - Switch LLM model

### Trace Table (Right Panel)

**Per-step breakdown of cost:**

| Step | Meaning | Latency | Cost |
|---|---|---|---|
| `embed_query` | Turn question into vector | ~10ms (local) / 100ms (API) | ~$0 |
| `dense_search` | Vector DB finds chunks | ~5ms | $0 |
| `keyword_search` | SQLite FTS5 finds matches | ~2ms | $0 |
| `exact_search` | SQLite lookup on symbols | ~1ms | $0 |
| `fuse` | Merge ranked lists | ~5ms | $0 |
| `rerank` | Cross-encoder re-scores | ~50ms (if on) | ~$0 |
| `prompt` | Build context + instructions | ~10ms | $0 |
| `generate` | LLM writes answer | 500ms–2s | Bulk of cost |

**Use trace to:**
- Spot bottlenecks (e.g., embedding taking 500ms)
- See token counts (e.g., "prompt was 1200 tokens, answer was 180 tokens")
- Calculate cost per query (summed from all steps)

---

## Debugging & Tuning Strategies

### When Latency Is Too High

1. **Check the trace**: Which step is slow?
   - If `embed_query` is slow: switch to local embedding (fastembed) or cache embeddings
   - If `generate` is slow: lower `max_tokens` or switch to a faster LLM
   - If `dense_search` is slow: switch to HNSW, reduce `candidates`

2. **Reduce throughput:**
   - Lower `top_k` (e.g., 10 → 5)
   - Lower `candidates` (e.g., 40 → 20)
   - Skip reranking (saves ~50ms)
   - Reduce `max_tokens` (shorter answers)

3. **For bulk indexing:**
   - Increase `batch_size` in the Embed node
   - Run on a machine with GPU (if using API embeddings)

### When Quality Is Poor

1. **Check retrieval first** (80% of problems are here):
   - Open the inspector. Are the right chunks in top-5?
   - If no: retrieval is failing. Try:
     - Larger `top_k` (more shots on goal)
     - Better embedding model (bge-small → bge-base → Gemini)
     - Smaller chunk size (more specific boundaries)
     - Structure-aware chunking (respect headings)
   - If yes: go to step 2.

2. **Check context inclusion:**
   - Are retrieved chunks making it into the prompt?
   - If chunks say "In context: ✗": increase `max_context_tokens`

3. **Check LLM synthesis:**
   - Are chunks in the prompt but answer still bad?
   - Try:
     - Lower temperature (force focus)
     - Add a prompt template that's more specific
     - Switch to a more capable LLM (Gemini 2.5 → better reasoning)

### When You Get Hallucinations

- Lower `temperature` (e.g., 0.5 → 0.1)
- Enable `say_dont_know` (tell LLM to refuse unanswerable)
- Increase `min_score` threshold (drop low-confidence dense results)
- Reduce `max_context_tokens` (less noisy input)
- Enable reranking (filter to truly relevant chunks)

### When You Want Reproducible Answers

- Set `temperature` to 0.0 (deterministic LLM output)
- Use local embedding (`fastembed`, deterministic)
- Use exact vector store (`faiss-flat` or `numpy`)
- Document the pipeline version (for repeatability)

---

## API Reference

### Endpoint

```
POST /api/projects/{project_id}/chat
```

### Request

```json
{
  "question": "How do I make a field optional?",
  "version_id": "optional UUID to use specific version",
  "stream": false
}
```

### Response (Streaming: SSE)

With `stream: true`, the response is Server-Sent Events. Each event is one of:

```
event: status
data: {"message": "Building index...", "job_id": "..."}

event: run
data: {"run_id": "...", "version": 1, "build_id": "...", "store": "faiss"}

event: retrieval
data: {"results": [...], "trace": [...]}

event: token
data: "The"

event: done
data: {
  "answer": "The answer text...",
  "citations": [...],
  "retrieved": [...],
  "trace": [...],
  "totals": {
    "ms": 1234,
    "tokens_in": 245,
    "tokens_out": 35,
    "cost_usd": 0.0089
  },
  "truncated": false
}
```

### Response (JSON)

With `stream: false`:

```json
{
  "answer": "To make a field optional... [1]",
  "citations": [
    {
      "n": 1,
      "chunk_id": "...",
      "document": "pydantic.pdf",
      "page_start": 42,
      "page_end": 42,
      "spans": [[10, 50]]
    }
  ],
  "sources": [
    {
      "rank": 1,
      "document": "pydantic.pdf",
      "page_start": 42,
      "found_by": ["dense", "keyword"],
      "text": "Optional fields...",
      "cited": true
    }
  ],
  "totals": {
    "ms": 1234,
    "tokens_in": 245,
    "tokens_out": 35,
    "cost_usd": 0.0089
  }
}
```

### Example curl

```bash
curl -X POST http://127.0.0.1:8000/api/projects/abc123/chat \
  -H "content-type: application/json" \
  -d '{
    "question": "How do I make a field optional?",
    "stream": false
  }'
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| **"No LLM API key configured"** | Add `GEMINI_API_KEY` or `NVIDIA_API_KEY` to `.env`. Get free keys from [Google AI Studio](https://aistudio.google.com/apikey) or [NVIDIA build.nvidia.com](https://build.nvidia.com). |
| **Embedding download stalls** | First run downloads ~70 MB model. Check internet connection. Models cached in `data/models`. |
| **Vector store errors after switching** | Vector store type change requires rebuild. Click "Build Index" on Configure page. Old vectors cached; switch back and they're re-used. |
| **"Document failed to index"** | Check the Documents tab for error. May be: unsupported format, corrupted file, or OCR failure. Try re-uploading or converting to PDF. |
| **Slow indexing on large corpus** | Increase embedding `batch_size` (e.g., 32 → 64). Use local embeddings (`fastembed`) instead of APIs. Use exact vector stores (FAISS Flat > HNSW). |

---

## Next Steps

- **Phase 2** (future): Auto-generate eval sets, run parameter sweeps, see a Pareto leaderboard of best configs, identify corpus gaps
- **Phase 3** (future): Agentic retrieval, query decomposition, injection resistance testing, embed adapters

For now, focus on **upload → configure → chat → inspect**. Use the Versions tab to track what works.

---

## Questions?

See the main [README.md](README.md) for architecture and testing. See [PRD.md](PRD.md) for the full product specification including Phase 2 & 3 plans.
