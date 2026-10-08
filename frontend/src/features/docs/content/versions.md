# Versions

Every saved pipeline is an immutable version. The Versions tab is the history of your project's configuration, and the place to roll back, compare and export.

## How versions work

- **Immutable.** Editing never rewrites a version; saving creates the next one (v1, v2, v3 ...).
- **One is active.** The Playground and the API answer with the active version. Switching which one is active is instant for instant settings; if the target needs a different index, RAGLabs builds or reuses it.
- **Nothing is lost.** Every switch is recorded in the version's activation history, so you can see when a version was live.

## The version list

Versions are listed newest first. Select one to see:

- its **note** and when it was created,
- **changes from parent**: exactly which fields differ from the version it was based on, with Instant and Rebuild badges,
- the **full configuration** as JSON,
- the **index status** for that version's index (ready, stale, building, failed or not built),
- its **activation history**.

## Make a version active

Select a version and choose **Make active**. The Playground and API use it from the next question. If the version needs an index that does not exist yet, the project header shows the build progress. Because indexes are cached by content, going back to an older configuration usually reuses its index immediately.

## Compare two versions

On a version's page, choose another version to compare against (by default it compares with its parent; the first version compares with the active one). The table, headed *Changes vs vN*, lists each changed field with its before and after values and its effect (Instant or Rebuild). To compare how well they perform, score both on the same eval set in [Evaluate](/docs/evaluate), or sweep them in [Sweeps](/docs/sweeps).

## Save as recipe

**Save as recipe** keeps the pipeline in the recipe gallery, where you can share it as a link or fork it into another project. See [Configure](/docs/configure).

## Export RAG

**Export RAG** downloads a standalone Python project with this version's index and pipeline. It runs without RAGLabs: a small FastAPI server answers `POST /chat` with an answer and its sources, using your own LLM key from the exported `.env`.

The export includes the retrieval features you configured, for example fused retrieval with exact matching, query expansion, context windows, agentic search, query decomposition, the embedding adapter and prompt optimisation results, and injection defences. It does not include the grounding check or the code check.

| | API tab | Export RAG |
| --- | --- | --- |
| Runs on | Your RAGLabs backend | Any machine with Python |
| Configuration changes | Picked up live | Frozen at export time |
| LLM key | The server's configuration | The developer's own `.env` |
| Best for | Apps that call your pipeline over HTTP | Shipping the pipeline inside another project |

## Regression guard

Once a project has an eval set, every version you save on the Configure tab is scored on the newest set automatically. The save message says so, and the run appears in Evaluate's run history with arrows against the previous run. A change that makes retrieval worse is therefore visible immediately. See [Evaluate](/docs/evaluate).
