# Configure

The Configure tab edits the pipeline. Every change you save becomes a new [version](/docs/versions).

## Editing a pipeline

The tab has two views of the same configuration.

- **Stages** is a form per stage, in pipeline order. Each field has a plain-language explanation and an **Instant** or **Rebuild** badge so you know what saving costs. Problems are highlighted on the field and summarised at the top.
- **Canvas** draws the pipeline as it actually runs: the query lane with its parallel retrieval paths, the index lane that feeds them, and the early exits and loops (cache hit, attested computation, the agent's search loop, the grounding-check retry). Drag nodes to arrange them (the layout is remembered per project), drop a type from the palette onto a node, toggle retrieval paths, and click a node to edit it.

> **Note** The canvas keeps the stages in their order. RAGLabs does not rewire them into free-form graphs, so every configuration stays comparable and can be scored the same way.

You are always editing a **draft**. Nothing changes for the Playground and API until you save.

## Saving

1. Optionally write a note for the version. Without one, RAGLabs writes a note describing what changed, for example "retrieve type hybrid → keyword".
2. Click **Save changes**. If nothing changed from the active version, nothing is saved.
3. The new version becomes active. If it only changed instant settings, it is live immediately. If it changed rebuild settings, the index updates first; the toast tells you which.

Before saving you can see an **estimate** of the work: whether a rebuild is needed, and roughly how many chunks will be embedded or reused from cache.

If the project already has an eval set, the new version is also scored on it automatically, and the result appears in [Evaluate](/docs/evaluate) with arrows showing the change from the previous run (the regression guard).

## Describe a change

Instead of finding the right fields, type what you want, for example *add a reranker and switch to hybrid*. The model only proposes changes to named fields (`slot.field`); the server applies and validates them, with one repair round if something is invalid. The proposed draft appears with its Instant and Rebuild badges before you apply it, and the changed stages (or canvas nodes) light up. Saving a rebuild change re-indexes your documents, and the panel says so.

## Recommended starting points

The **recommended pipeline** is the default for a new project: PyMuPDF4LLM parsing, structure-aware chunks of 1,000 characters with 150 overlap, the local `bge-small` embedding model, an exact FAISS index, fused retrieval with `top_k` 8, no reranker, a cited-answer prompt, and the first LLM provider you have connected. You can reset the draft to it at any time (unsaved edits are lost, and RAGLabs asks first).

The **Recipes** page (top bar) offers seven built-in starting points and any recipes you saved:

| Recipe | For |
| --- | --- |
| Fast and cheap | Low latency and small prompts |
| Hybrid plus rerank | A strong general default |
| Technical docs | Code, error messages and identifiers |
| Multi-part questions | Questions with several parts (query decomposition) |
| Agentic research | Hard questions that need several searches |
| Hardened for production | Injection defences and grounding check |
| FAQ bot with a cache | Repeated questions answered without a model call |

Pick a project to apply a recipe to. A share link carries the recipe itself, so it works on any install. When forking into a project, RAGLabs drops a corpus-specific adapter and keeps the project's own LLM if the recipe's provider is not connected, and tells you.

## Tuning guide

If you are not sure where to start, these are the settings that matter most.

| Symptom | Likely cause | Try |
| --- | --- | --- |
| Answers are generic or miss details | Chunks too large | Smaller chunk size, or structure-aware chunking |
| Answers are disjointed | Chunks too small or cut mid-thought | Larger size, more overlap |
| The right passage is not in the top results | Weak embedding model or too few results | A stronger embedding model, higher `top_k`, or a reranker |
| Error messages and symbols are not found | Meaning-only search | The `fused` retriever, with a higher exact weight |
| The right passage was found but ignored | It did not fit the prompt | Raise **Max context tokens** or add a reranker |
| Made-up facts | Temperature too high or noisy context | Lower the temperature, enable "say I don't know", add a grounding check |

Rather than guessing, [evaluate](/docs/evaluate) the current version first. The diagnoses tell you which of these rows applies, and [Sweeps](/docs/sweeps) try many settings at once.

Every option of every stage is described in the [pipeline reference](/docs/pipeline-reference).
