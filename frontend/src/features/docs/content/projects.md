# Projects

A project is one corpus of documents plus every pipeline version, eval set and run that belongs to it.

## The projects page

The home page lists your projects as cards. Each card shows the number of documents, the number of chunks and the index status (ready, building, stale, failed or not built), so you can see at a glance which ones need attention. Use the search box to filter by name, and **New project** to start another.

A project card opens its workspace. Deleting a project asks for confirmation and removes its documents, indexes and history from `data/`; this cannot be undone.

## The create wizard

**New project** opens a wizard. Its state lives in the address bar, so reloading the page resumes where you were. The first screen asks what you want to do:

- **Build a RAG here** is the four steps below.
- **Evaluate a RAG I already have** is three steps: Name, Documents (upload the documents your RAG searches), then you land on Evaluate to generate questions and connect your endpoint. There is no Configure or Build step. See [Evaluate your own RAG](/docs/your-rag).

The four steps for building:

1. **Name.** A name and an optional description.
2. **Documents.** Upload files or add a URL. Nothing is indexed yet; you choose how in the next step. See [Documents](/docs/documents) for formats and options.
3. **Configure.** Start from the recommended pipeline or tune each stage. Rebuild settings apply when the index is built, instant settings at query time. Details in [Configure](/docs/configure).
4. **Build.** Review the estimate (for example "will embed 1,240 chunks, no re-embeddings") and start the build. Progress streams live, and when it finishes you can go straight to the Playground.

> **Note** Versions saved from the wizard are not scored automatically. The automatic re-scoring (the regression guard) applies to versions you save on the Configure tab once the project has an eval set.

## The project workspace

Inside a project, the header shows its name, the active version and the index status, and a **Build index** button when a rebuild is possible. The tabs are:

| Tab | Use it to |
| --- | --- |
| [Documents](/docs/documents) | Add, inspect, tag and remove source material |
| [Configure](/docs/configure) | Edit the pipeline and save versions |
| [Versions](/docs/versions) | Compare, activate and export saved pipelines |
| [Playground](/docs/playground) | Ask questions and inspect retrieval and cost |
| [Evaluate](/docs/evaluate) | Measure quality and run sweeps |
| [Health](/docs/health) | Find gaps and rot in the documents |
| [API](/docs/api) | Call the project from code, manage keys and see usage |
| [Computations](/docs/data) | Answer numeric questions exactly from tables |

The **Labs** switch under **LLM providers** reveals the embedding adapter and prompt optimisation tools in Evaluate.

## A provider banner

If no LLM provider is connected, a banner at the top of the workspace says so. Indexing and retrieval still work; only answering needs a model. See [LLM providers](/docs/providers).
