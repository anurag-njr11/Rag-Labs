# Quickstart

Go from nothing to a cited answer and a first quality score in about ten minutes.

## Before you start

You need [uv](https://docs.astral.sh/uv/) (it fetches the right Python for you) and Node.js 20 or newer. For chat you also need an LLM: a free Gemini or NVIDIA key is enough, and so is a local Ollama or LM Studio server. Retrieval and indexing work without any key.

## 1. Run the app

Open two terminals in the repository.

```bash
# Terminal 1: backend on http://127.0.0.1:8000
cd backend
uv sync
uv run uvicorn app.main:app
```

```bash
# Terminal 2: frontend on http://localhost:5173
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Optionally copy `.env.example` to `.env` first and paste a key such as `GEMINI_API_KEY`; you can also connect providers later under **LLM providers** in the top bar ([details](/docs/providers)).

> **Note** The first index build downloads a small local embedding model (about 70 MB). It is cached, so this happens once.

## 2. Create a project

1. On the home page choose **New project** and give it a name.
2. **Documents step.** Drop in PDF, DOCX, Markdown, text or HTML files, or add a URL. After parsing you see a parse-quality indicator for each file.
3. **Configure step.** Keep the recommended pipeline for now. Every stage can be tuned later.
4. **Build step.** Review the estimate and start the build. Progress streams live: parse, embed, store, keywords.

## 3. Chat and inspect

Open the **Playground** and ask a question about your documents. The answer streams in with `[1]`, `[2]` citation markers. Open the inspector to see the retrieved passages, which search path found each one, and whether it reached the prompt and was cited. The trace shows time, tokens and cost for every step. See [Playground](/docs/playground).

## 4. Measure it

1. Open the **Evaluate** tab and click **Generate eval set** (30 questions is a good default).
2. Click **Run evaluation**. You get Hit@1, Hit@3, Hit@k, MRR and latency, and every miss is diagnosed with a suggested fix.
3. Change something on **Configure**, save, and the new version is scored automatically so you can compare.

See [Evaluate](/docs/evaluate) for how to read the results.

## Try the demo project

To explore with ready-made content, seed the Pydantic documentation project:

```bash
cd backend
uv run python scripts/seed_demo.py
```

Then ask *How do I make a field optional with a default?* or paste a raw error message such as `Input should be a valid integer, unable to parse string as an integer`. The top source carries an **exact** badge because exact-match lookup caught the error text.

## Next steps

- Learn the vocabulary in [Core concepts](/docs/concepts).
- Tune the pipeline in [Configure](/docs/configure).
- Compare many configurations at once in [Sweeps](/docs/sweeps).
- Call your project from code in the [API tab](/docs/api).
