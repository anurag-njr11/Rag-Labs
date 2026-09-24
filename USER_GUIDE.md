# RAGLabs User Guide

**Build, Chat & Evaluate:** Upload documents, tune every pipeline parameter, chat with cited answers, inspect retrieval — and measure how well each configuration retrieves, with test questions generated from your own documents (no labelling).

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Core Concepts](#core-concepts)
3. [Step-by-Step Tutorial](#step-by-step-tutorial)
4. [Pipeline Configuration Guide](#pipeline-configuration-guide)
5. [Using the Playground](#using-the-playground)
6. [Evaluating Your Pipeline](#evaluating-your-pipeline)
7. [Debugging & Tuning Strategies](#debugging--tuning-strategies)
8. [API Reference](#api-reference)

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
- Go back to an old version with **Make active** (each switch is kept in its activation history)
- Never rewrite history

### Content-Addressed Caching

The system caches at every stage:
- Chunks are keyed by (parse config + chunk config + document hash)
- Vectors are keyed by (chunks + embedding config)

**Result**: Switching vector stores never re-embeds. Changing `top_k` doesn't rebuild.

### Eval Sets

An **eval set** is a list of test questions written automatically from your documents. Each question comes with the correct answer and an **exact quote** from the source that contains it. A version is scored by where the passage containing that quote lands in its search results. Because questions are tied to a quote, not to a particular chunk, one eval set can compare versions that chunk the documents differently. See [Evaluating Your Pipeline](#evaluating-your-pipeline).

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

## Evaluating Your Pipeline

The **Evaluate** tab (between Playground and API) answers "is this configuration any good?" with numbers instead of a few hand-picked test questions. You don't write or label any questions.

### How It Works

1. **Sample**: passages are picked evenly from every document in the index. Very short passages and tables are skipped.
2. **Write questions**: your configured LLM (the Generate stage's provider and model) writes one question per passage, along with the answer and an exact quote from the passage.
3. **Filter**: a question is dropped if:
   - its quote isn't really in the passage, or
   - the model can answer it with **no documents at all**. That question would test the model's memory, not your retrieval.
4. **Score**: each remaining question is run through a version's Retrieve and Rerank stages. The score is where the first passage containing the quote lands. No LLM is used for scoring, so it's free and gives the same numbers every time.

### Step by Step

1. Open a project with a built index → **Evaluate** tab.
2. Choose a size (10, 20, 30 or 50 questions; 30 is a good default) → click **Generate eval set**.
   - Progress shows *Write questions* → *Filter generic questions*. If the index is out of date, it's rebuilt first.
3. Review the set:
   - The badges show how many questions were **kept**, and how many were rejected as **too generic** or for **bad evidence**.
   - Expand **Questions** and click any question to see its answer, the quoted evidence, and what the model said without documents.
   - Expand **Rejected by the filter** to see what was dropped and why.
4. Under **Retrieval quality**, pick a version (the active one by default) → **Run evaluation**.
5. Change the configuration on the Configure tab and save a new version. Then come back, pick that version, and run again. Each run adds a row to the comparison table.

### Reading the Results

| Metric | Meaning | Good sign |
|---|---|---|
| **Hit@1** | Share of questions where the right passage was ranked **first** | High |
| **Hit@3** | ...ranked in the top 3 | High |
| **Hit@k** | ...made it into the final **k** results, the ones that reach the prompt. k = `top_k`, or reranker `top_n` when reranking is on | As close to 100% as possible |
| **MRR** | Average of 1 / rank; 1.0 means always first, 0 means never found | Closer to 1.0 |
| **Retrieval p50** | Median time to retrieve (and rerank) one question | Low |

In the runs table, **▲ / ▼** show the change from the previous run in percentage points. Click a row to see its details.

### Why a Question Missed

Every miss gets a diagnosis and a suggested fix:

| Diagnosis | What happened | Try |
|---|---|---|
| **Dropped by reranker** | Retrieval found the passage, but the reranker cut it | Raise the reranker's **Keep top N** (`top_n`) |
| **Ranked below top-k (#n)** | The passage was found at rank *n*, below your cut-off | Raise `top_k`, or add a reranker to lift it |
| **Not retrieved** | The passage isn't in the top 50 at all | Try another retriever (e.g. `fused`), a better embedding model, or different chunking |

Tick **Only misses** to list just the failures.

### Tips

- **Compare, don't brag.** Generated questions often reuse the document's wording, so absolute scores run a little optimistic. The real value is comparing versions on the **same** eval set.
- **Mind the sample size.** With 20–30 questions, a difference under about 10 points may be noise. Use 50 questions for closer calls.
- **Instant changes are cheap to test.** Retriever type, `top_k`, weights and the reranker don't need a rebuild, so you can compare them right away. Rebuild changes like chunking or the embedding model build the new index automatically on the first run.
- **Regenerate after big document changes.** Questions whose source document was deleted will always miss.
- **Cost and privacy.** Generating 30 questions takes about 14 LLM calls, and document passages are sent to your LLM provider. Scoring runs entirely on your machine.

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

1. **Check retrieval first** (if the right passage never reaches the prompt, nothing later can fix the answer):
   - Run an evaluation on the **Evaluate** tab to measure this across many questions at once. The miss diagnoses tell you which fix below applies.
   - For a single question, open the inspector. Are the right chunks in top-5?
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

### Using the API Tab

The **API** tab (the last tab in a project) turns your project into an HTTP service. Any script or app can send a question to the project and get back the same cited answer you see in the Playground. It uses the project's **active version**, so when you change the configuration or switch versions, callers get the new behaviour with no code change.

#### Before You Start

- The backend is running (`uv run uvicorn app.main:app` in `backend/`, serving `http://127.0.0.1:8000`).
- The project has documents and an active version. The Playground should already answer questions.
- An LLM key (`GEMINI_API_KEY` or `NVIDIA_API_KEY`) is set in the **server's** `.env`. Callers don't need a key.

#### Step 1: Open the API Tab

1. Open your project.
2. Click the **API** tab in the top bar (after Evaluate).

The page has five cards: **Query endpoint**, **Request**, **Response**, **Try it** and **Notes**.

#### Step 2: Copy Your Endpoint

The **Query endpoint** card shows your project's URL, already filled in:

```
POST http://127.0.0.1:8000/api/projects/<your-project-id>/chat
```

Click the copy button next to it. The project ID is the same one in your browser's address bar (`/projects/<your-project-id>/api`).

The request body is JSON:

| Field | Required | Meaning |
|---|---|---|
| `question` | Yes | Your question, 1–8000 characters |
| `version_id` | No | Answer with a specific version instead of the active one (see Step 6) |
| `stream` | No | `false` returns one JSON response. `true` (the default) streams the answer as Server-Sent Events (see Step 7) |

#### Step 3: Test It in the App

1. Scroll to the **Try it** card.
2. Type a question about **your** documents. The box starts with a Pydantic example question; replace it.
3. Click **Send request**.
4. After a few seconds the raw JSON response appears: exactly what your code will receive.

If it fails, a red banner shows the error (see [Errors](#errors) below).

#### Step 4: Call It From Your Code

The **Request** card has ready-made snippets with your URL filled in. Pick **curl**, **Python** or **JavaScript**, click the copy button, and change the question.

**curl** (macOS, Linux, Git Bash):

```bash
curl -X POST http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the dataset about?", "stream": false}'
```

**Windows PowerShell** (the curl snippet's quoting doesn't work in PowerShell, so use this instead):

```powershell
$body = @{ question = "What is the dataset about?"; stream = $false } | ConvertTo-Json
$res = Invoke-RestMethod -Method Post -ContentType "application/json" -Body $body `
  -Uri "http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat"
$res.answer
```

**Python** (`pip install requests` first):

```python
import requests

res = requests.post(
    "http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat",
    json={"question": "What is the dataset about?", "stream": False},
    timeout=120,
)
res.raise_for_status()
data = res.json()
print(data["answer"])
for c in data["citations"]:
    print(f"[{c['n']}] {c['document']} — {c['heading_path']}")
```

**JavaScript** (Node 18+ or a server-side app; for browser pages see [Limits](#limits)):

```js
const res = await fetch("http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question: "What is the dataset about?", stream: false }),
})
if (!res.ok) throw new Error((await res.json()).detail?.message ?? res.statusText)
const { answer, citations } = await res.json()
```

#### Step 5: Read the Response

The **Response** card shows a real response from your latest successful run (long fields trimmed), so you can see the shape with your own data. The fields are:

| Field | What it holds |
|---|---|
| `answer` | The answer text, with citation markers like `[1]` |
| `citations` | One entry per marker: `n` (the number in `[n]`), `document`, `page_start`/`page_end`, `heading_path`, and `spans`: character ranges in the cited chunk that support the claim |
| `sources` | Every retrieved chunk in rank order: `rank`, `document`, pages, `heading_path`, `found_by` (`dense`/`keyword`/`exact`), `scores`, `cited` (true if the answer cites it) and `text` |
| `run_id` | ID of this run. It appears in the Playground's **History** (see Step 8) |
| `totals` | `latency_ms`, `tokens_in`, `tokens_out`, `cost_usd` |

To show sources to your users, loop over `citations` and match each `n` to the `[n]` markers in `answer`.

#### Step 6: Pin a Version (Optional)

By default every call uses the active version. To keep a caller on one version while you experiment with others:

1. Open the **Versions** tab and click the version you want.
2. Copy its ID from the address bar: it's the value after `?v=`. You can also list all versions with `GET /api/projects/YOUR_PROJECT_ID/versions`.
3. Add it to the request body: `{"question": "...", "version_id": "THE_VERSION_ID", "stream": false}`.

Leave out `version_id` to follow whichever version is active.

#### Step 7: Stream the Answer (Optional)

For a chat UI that shows the answer as it's written, send `"stream": true`. The **Streaming** snippet on the Request card shows the curl version. The response is a stream of events:

`status` (only if the index is being rebuilt) → `run` → `retrieval` → `token` (many) → `done`, or `error`

Each event's `data:` line is JSON with a `type` field. The endpoint is a `POST`, so browsers' `EventSource` can't read it; read the stream with an HTTP client instead:

```python
import json
import requests

with requests.post(
    "http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat",
    json={"question": "What is the dataset about?", "stream": True},
    stream=True,
    timeout=300,
) as res:
    res.raise_for_status()
    for line in res.iter_lines(decode_unicode=True):
        if not line.startswith("data:"):
            continue  # skip "event:" lines and blank separators
        event = json.loads(line[5:])
        if event["type"] == "token":
            print(event["text"], end="", flush=True)
        elif event["type"] == "done":
            print("\n\nSources:")
            for c in event["citations"]:
                print(f"[{c['n']}] {c['document']} — {c['heading_path']}")
        elif event["type"] == "error":
            raise RuntimeError(event["message"])
```

#### Step 8: Check Your Calls

Every API call is recorded as a run, just like a Playground question:

- **Playground → History** lists API calls alongside chat questions. Open one to inspect its retrieved chunks and trace table (latency, tokens and cost per step).
- The API tab's **Response** card always shows your latest successful run.

#### Errors

Errors come back as JSON with a `detail` field:

| Status | Meaning | Fix |
|---|---|---|
| `404` | Project or `version_id` not found | Check the IDs in the URL and body |
| `409` | The project has no documents, or its index build failed | Add documents on the Documents tab, or fix the build |
| `422` | Invalid body, e.g. empty `question` | Send `{"question": "..."}` with 1–8000 characters |
| `502` | The LLM provider failed (no key, rate limit, overload) | Check the server's `.env` key and retry, or switch the Generate provider |

In streaming mode, errors arrive as an `error` event: `{"type": "error", "code": "...", "message": "..."}`.

#### Limits

- **Local only.** The server listens on `127.0.0.1`, so only your own machine can call it. To reach it from another machine, start it with `uv run uvicorn app.main:app --host 0.0.0.0` and use your machine's IP. There's **no authentication**, so anyone who can reach the port can use your LLM key; only do this on a network you trust.
- **No browser calls from other sites.** The backend doesn't send CORS headers, so JavaScript on another web page (another origin) is blocked by the browser. Call the API from a server, script or Node app instead.
- **The first call after a rebuild-type change is slow.** If you changed a 🔁 Rebuild setting, the first call rebuilds the index before answering (a `status` event when streaming).

#### API Tab or Export RAG?

| | API tab | Export RAG (Versions tab) |
|---|---|---|
| Runs on | Your RAGLabs backend | Any machine with Python |
| Config changes | Picked up live | Frozen at export time |
| LLM key | The server's `.env` | The developer's own `.env` |
| Best for | Apps that call your pipeline over HTTP | Shipping the pipeline into another project |

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
data: {"type": "token", "text": "The"}

event: done
data: {
  "type": "done",
  "run_id": "...",
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
      "document_id": "...",
      "document": "pydantic.pdf",
      "page_start": 42,
      "page_end": 42,
      "heading_path": "Fields > Optional fields",
      "spans": [[10, 50]]
    }
  ],
  "sources": [
    {
      "rank": 1,
      "document": "pydantic.pdf",
      "page_start": 42,
      "page_end": 42,
      "heading_path": "Fields > Optional fields",
      "found_by": ["dense", "keyword"],
      "scores": {"dense": 0.82, "keyword": 7.1},
      "cited": true,
      "text": "Optional fields..."
    }
  ],
  "run_id": "...",
  "totals": {
    "ms": 1234,
    "latency_ms": 1234,
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

### Evaluation Endpoints

All paths are under `/api/projects/{project_id}/eval`. Generating a set and running an evaluation start background jobs. Follow their progress at `GET /api/jobs/{job_id}/events` (SSE), or poll the set or run until `status` is `ready` or `failed`.

| Method & path | Body | Returns |
|---|---|---|
| `POST /sets` | `{"size": 30, "version_id": "optional"}` | `{eval_set, job_id}` |
| `GET /sets` | | All eval sets, newest first |
| `GET /sets/{set_id}` | | The set plus its `items` (question, answer, evidence, `valid`, `reject_reason`) |
| `POST /sets/{set_id}/runs` | `{"version_id": "optional, default active"}` | `{run, job_id}` |
| `GET /runs?set_id=...` | | Runs with `metrics` (`hit_at_1`, `hit_at_3`, `hit_at_k`, `mrr`, `p50_ms`, `diagnoses`, `config`) |
| `GET /runs/{run_id}` | | One run plus per-question `results` (`rank`, `hit`, `diagnosis`, `deep_rank`) |

```bash
# Generate a 30-question eval set
curl -X POST http://127.0.0.1:8000/api/projects/abc123/eval/sets \
  -H "content-type: application/json" -d '{"size": 30}'

# Score the active version against it
curl -X POST http://127.0.0.1:8000/api/projects/abc123/eval/sets/SET_ID/runs \
  -H "content-type: application/json" -d '{}'
```

Full response shapes are in [frontend/API.md](frontend/API.md) under "Evaluation".

---

## Troubleshooting

| Issue | Solution |
|---|---|
| **"No LLM API key configured"** | Add `GEMINI_API_KEY` or `NVIDIA_API_KEY` to `.env`. Get free keys from [Google AI Studio](https://aistudio.google.com/apikey) or [NVIDIA build.nvidia.com](https://build.nvidia.com). |
| **Embedding download stalls** | First run downloads ~70 MB model. Check internet connection. Models cached in `data/models`. |
| **Vector store errors after switching** | Vector store type change requires rebuild. Click "Build Index" on Configure page. Old vectors cached; switch back and they're re-used. |
| **"Document failed to index"** | Check the Documents tab for error. May be: unsupported format, corrupted file, or OCR failure. Try re-uploading or converting to PDF. |
| **Slow indexing on large corpus** | Increase embedding `batch_size` (e.g., 32 → 64). Use local embeddings (`fastembed`) instead of APIs. Use exact vector stores (FAISS Flat > HNSW). |
| **"Could not generate an eval set" / rate limit** | Generation calls your LLM about 14 times for 30 questions. On a free tier, wait a minute and retry, pick a smaller size, or switch the Generate provider. |
| **Few questions kept** | Your documents may cover general knowledge the model already knows (rejected as *too generic*), or be mostly short or table-only passages. Add more specific documents or generate a larger set. |
| **Eval set or run shows "Interrupted by a server restart"** | Restarting the backend cancels running jobs. Click **Generate** or **Run evaluation** again. |
| **A question always misses and its source shows "—"** | Its source document was deleted. Regenerate the eval set. |

---

## Next Steps

- **Available now**: auto-generated eval sets, repeatable retrieval scoring, a diagnosis for every miss, and side-by-side version comparison (Evaluate tab)
- **Phase 2** (next): automatic sweeps over many configurations, a leaderboard of quality against cost, answer-quality scoring, and reports of gaps and contradictions in your documents
- **Phase 3** (future): Agentic retrieval, query decomposition, injection resistance testing, embed adapters

The recommended loop is **upload → configure → chat → inspect → evaluate**. Use the Versions tab to keep what works, and the Evaluate tab to prove it.

---

## Questions?

See the main [README.md](README.md) for architecture and testing. See [PRD.md](PRD.md) for the full product specification including Phase 2 & 3 plans.
