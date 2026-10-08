# Introduction

RAGLabs is a workbench for building, inspecting and measuring RAG (retrieval-augmented generation) systems: upload documents, tune every stage of the pipeline from a web UI, chat with cited answers, and find out with numbers whether a change made things better.

## What you can do with it

- **Build** a "chat with your documents" assistant without writing code. Pick how documents are parsed, chunked, embedded, stored, retrieved, reranked and answered, and every setting is explained and versioned.
- **Inspect** any answer. The Playground shows which passages were found, by which search path, which ones reached the prompt, which ones the answer cited, and what each step cost in time, tokens and money.
- **Measure** a configuration. RAGLabs writes test questions from your own documents, scores retrieval (Hit@k, MRR, nDCG), optionally grades answers, and tells you why each miss happened.
- **Optimise** with evidence. Sweep many configurations at once, see the quality-versus-cost frontier, and promote the winner in one click.
- **Fix the content**, not only the settings. Corpus Health shows what your documents cannot answer, and where they contradict themselves or have gone stale.
- **Evaluate a RAG you already have.** Point RAGLabs at any HTTP endpoint and score it on the same questions. See [Evaluate your own RAG](/docs/your-rag).
- **Ship it.** Call the project over HTTP, or export a standalone Python project that runs without RAGLabs.

## The loop

Most work in RAGLabs follows one loop:

1. **Upload** documents ([Documents](/docs/documents)).
2. **Configure** a pipeline ([Configure](/docs/configure)); each saved change becomes a [version](/docs/versions).
3. **Chat and inspect** in the [Playground](/docs/playground).
4. **Evaluate** the version with generated questions ([Evaluate](/docs/evaluate)) and fix what the diagnoses point to.
5. **Compare** configurations with [Sweeps](/docs/sweeps), promote the best.
6. **Health-check** the documents themselves ([Corpus Health](/docs/health)) and feed real questions back in.

> **Tip** If you only have five minutes, follow the [Quickstart](/docs/quickstart): it takes you from an empty project to a cited answer and a first score.

## How these docs are organised

- **Get started** covers installation, your first project and the vocabulary used everywhere else.
- **Project workspace** has one page per tab you use to build: Projects, Documents, Configure, Versions and Playground.
- **Measure & improve** covers Evaluate, Sweeps, your own RAG, the advanced evaluation tools and Corpus Health.
- **Integrate** covers the API tab, computations on tables, LLM providers and the command line.
- **Reference** lists every pipeline stage and option, the metric definitions, and fixes for common problems.

## Where your data goes

RAGLabs runs on your machine. Documents, indexes, eval sets and run history are stored under the repository's `data/` folder. Text leaves your machine only when you choose an LLM or an API embedding model: passages and questions are sent to that provider to write answers, generate eval questions or grade answers. Retrieval scoring itself runs locally and uses no LLM. API keys you enter in the app are encrypted at rest; see [LLM providers](/docs/providers).
