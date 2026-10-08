# Core concepts

The handful of ideas that the rest of RAGLabs is built on.

## RAG in one paragraph

A RAG system answers a question in two phases. **Retrieval** finds the passages of your documents that are most likely to contain the answer. **Generation** gives those passages to a language model and asks it to answer using only them. If retrieval misses, nothing downstream can recover; that is why RAGLabs spends so much effort on measuring retrieval.

## The pipeline

A pipeline is a list of **stages** (RAGLabs calls them slots). Each stage has a type and options. The default order is:

| Stage | What it does |
| --- | --- |
| Parse | Turns PDF, DOCX and HTML into Markdown text |
| Chunk | Splits text into passages |
| Embed | Turns each passage into a vector |
| Vector store | Stores and searches the vectors |
| Cache | Optionally reuses the answer to a near-identical earlier question |
| Compute | Optionally answers numeric questions exactly from a data table |
| Retrieve | Finds candidate passages (dense, keyword, exact, fused or agentic) |
| Rerank | Optionally re-scores the candidates with a cross-encoder |
| Prompt | Builds the prompt and decides how much context fits |
| Generate | The LLM that writes the answer |
| Verify | Optionally checks the answer against its sources |

The first four stages build the **index**; the rest run for every question. A pipeline is stored as one JSON document, so it can be saved, diffed, shared and exported. Every option is listed in the [pipeline reference](/docs/pipeline-reference).

## Instant and rebuild settings

Each option carries a badge that tells you what changing it costs:

- **Instant** settings apply at query time. Changing `top_k`, the reranker or the temperature needs no re-indexing.
- **Rebuild** settings change the index: the parser, chunking, the embedding model or the vector store type. RAGLabs rebuilds the index when you save, reusing cached work wherever it can.

## Versions

A saved pipeline is a **version**, and versions are immutable. Editing and saving creates a new one. Exactly one version is **active**: the Playground and the API use it. You can diff two versions, make an old one active again, and see when each switch happened. See [Versions](/docs/versions).

## Caching

Work is cached by content. Parsed text is keyed by the file and the parse settings; vectors by the chunks and the embedding settings. So switching the vector store never re-embeds, and changing `top_k` never rebuilds anything.

## Retrieval paths

Retrieval can use several search paths at once, and the inspector shows which one found each passage:

- **Dense** searches by meaning, using vectors.
- **Keyword** searches by words (BM25, full text).
- **Exact** looks up error messages, code symbols and identifiers verbatim.

The default retriever, `fused`, combines all three with rank fusion. See [Retrieve options](/docs/pipeline-reference).

## Eval sets and evidence

An **eval set** is a list of test questions generated from your own documents. Each question has an expected answer and a verbatim **evidence** quote from the source. A retrieved passage counts as a hit when it contains the evidence and comes from the right document. Because questions are tied to a quote rather than to one chunk, the same set can compare configurations that chunk the documents differently. See [Evaluate](/docs/evaluate).

## Diagnosis

Every missed question gets one diagnosis, most upstream cause first: the evidence was never retrieved, ranked below the cut-off, dropped by the reranker, cut by the context budget, or reached the model but the answer was still wrong. Each diagnosis comes with the setting to change. See [Why a question missed](/docs/evaluate).

## Where things live

| What | Where |
| --- | --- |
| Documents, indexes, eval sets, run history | `data/` in the repository (never committed) |
| Provider keys entered in the app | The local database, encrypted with a key kept in your user config folder |
| Pipeline configs | The database, one row per version (a version can also be exported as a standalone project) |
