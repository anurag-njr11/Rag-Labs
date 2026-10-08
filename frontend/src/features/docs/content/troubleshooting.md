# Troubleshooting

Common problems and what to do about them. If a problem is about answer quality rather than an error, start with [Evaluate](/docs/evaluate): its diagnoses tell you which setting to change.

## Setup and providers

| Problem | What to do |
| --- | --- |
| **No LLM provider configured** (banner in the workspace) | Connect one under **LLM providers**, or set a key such as `GEMINI_API_KEY` in `.env`. Free keys: Google AI Studio and build.nvidia.com. Indexing and retrieval work without one; answering does not |
| **The first build is slow, or the embedding download stalls** | The first run downloads a local model (about 70 MB for the default). Check your connection; models are cached and downloaded once |
| **A provider fails with a rate limit or overload** | Retry in a minute, pick a smaller eval-set size, or switch the Generate provider. Batch jobs (eval, grading) retry rate limits automatically with backoff; chat fails fast |
| **A provider key stopped working after I changed its URL** | A stored key is only sent to the base URL it was saved with. Enter the key again after changing the URL |
| **Stored keys are gone after moving machines** | Keys are encrypted with a master key in your user configuration folder. Copy that file, or set `RAGLABS_SECRET_KEY`, or re-enter the keys |
| **"Host not allowed" or a 400 from the backend** | The backend answers only to localhost host names. Add your host name to `ALLOWED_HOSTS` if you serve other machines |
| **401 from the API** | Requests from other machines need `Authorization: Bearer rl_...`. Create a key in the API tab |

## Documents and indexing

| Problem | What to do |
| --- | --- |
| **A document failed to index** | Open the Documents tab and read the error. Common causes: an unsupported format, a corrupted file, or OCR failure. Re-upload, or convert to PDF or Markdown |
| **Parse quality is poor** | A scan with no text layer yields nothing to retrieve. Try the `pymupdf_text` parser with OCR on (it needs Tesseract), or supply a text version |
| **Slow indexing on a large corpus** | Raise the embedding `batch_size`, use a local embedding model, and prefer exact stores (FAISS Flat) until the corpus is large |
| **Vector store errors after switching stores** | A store change needs an index build. Use **Build index**; vectors are cached, so switching back is instant |
| **The index shows "stale"** | Documents changed since the build. Build the index, or ask a question and it updates automatically |
| **"Interrupted by a server restart"** | Restarting the backend cancels running jobs. Start the build, eval or sweep again |

## Playground

| Problem | What to do |
| --- | --- |
| **Vague or generic answers** | Check the inspector: is the right passage retrieved? If not, raise `top_k`, try a stronger embedding model or smaller chunks. See [Playground](/docs/playground) |
| **The right passage is retrieved but marked dropped** | The context budget cut it. Raise **Max context tokens** or add a reranker |
| **The answer is cut off ("Incomplete")** | The token limit was hit. Raise `max_tokens`; reasoning models also spend tokens on thinking |
| **Slow answers** | Open the trace and find the slow step. See the tips in [Playground](/docs/playground) |
| **The first question after a change is slow** | A rebuild setting changed, so the index was rebuilt first |

## Evaluate

| Problem | What to do |
| --- | --- |
| **"Could not generate an eval set"** | Generation makes about 14 model calls for 30 questions. On a free tier, wait a minute and retry, or choose a smaller size |
| **Few questions kept** | Your documents may cover general knowledge the model already knows (rejected as too generic), or consist mostly of short or table-only passages. Add more specific documents, or generate a larger set |
| **A question always misses and its source shows a dash** | Its source document was deleted. Regenerate the eval set |
| **"That grid has N configurations; the limit is 48"** | Untick some sweep values; the count updates as you click |
| **A sweep row "couldn't run"** | Expand the list under the leaderboard to see why. Usually the combination is invalid (for example overlap not smaller than chunk size) or a model failed to download. Other rows are still valid |
| **Answer grades differ between runs** | Grades are judgements from a model. Retrieval metrics are exact; lead with those |
| **Scores look too good** | Generated questions often reuse the document's wording. Compare configurations on the same set rather than trusting absolute numbers |
| **A run says "edited since this run"** | The eval set changed after the run, so it scored a different set. Re-run before comparing |

## Your RAG and the CLI

| Problem | What to do |
| --- | --- |
| **"Couldn't reach ..."** | The endpoint is down or unreachable from the machine running RAGLabs, or the request timed out. Check the URL and the timeout |
| **"No list of contexts at 'contexts'"** | The response does not match the mapping. Use **Test with one question** and adjust the **Contexts path** |
| **"A context has no text at 'text'"** | The passages are objects with a different text key, or plain strings. Fix **Text path**; leave it empty if each context is a string |
| **Every question misses although your system answers well** | The system indexes different documents than the project, or its `source` values do not match file names. Clear **Source path** to judge on text alone |
| **"Pick a judge model"** | Answer grading on an external system needs a judge. Choose one in the **Judge model** menu |
| **The CLI exits with code 2** | Bad input or an unreachable endpoint; the message says which. See [CLI and CI](/docs/cli) |

## Code check and Docker

| Problem | What to do |
| --- | --- |
| **"Code checks: not run"** | Docker is not running. Start it to execute answers' code; RAGLabs never runs code locally |
| **The sandbox image is missing** | Pull the image (`python:3.12-slim` by default), or set `SANDBOX_IMAGE` to one that has the libraries your documents cover |

## Corpus Health

| Problem | What to do |
| --- | --- |
| **"Couldn't be graded"** | One batch of grading calls failed, often a rate limit. Run the check again |
| **Almost nothing is reported as unused** | With fewer than about 30 questions, unused mostly means nobody has asked yet |

## Still stuck?

Open an issue on the project's repository with what you did, what you expected and what happened, plus your OS, Python and Node versions, vector store and LLM provider. For security problems, follow `SECURITY.md` instead of opening a public issue.
