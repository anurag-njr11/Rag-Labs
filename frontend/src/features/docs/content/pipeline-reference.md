# Pipeline reference

Every stage, type and option in the pipeline, with its default. Options marked **instant** apply at query time; all others are **rebuild** settings that re-index when saved (see [Core concepts](/docs/concepts)). The Configure tab shows the same descriptions next to each field.

## Parse

Turns files into Markdown text. A rebuild stage.

| Type | Use it for |
| --- | --- |
| `pymupdf4llm` (default) | Best default: keeps headings and turns tables into Markdown tables |
| `pymupdf_text` | Fast plain-text extraction, optional table detection and OCR |
| `pypdf` | Simple pure-Python text extraction with no table or heading detection |

| Option | Default | Meaning |
| --- | --- | --- |
| `strip_headers_footers` | on | Remove lines repeated at the top or bottom of most pages |
| `extract_tables` (`pymupdf_text`) | on | Detect tables and emit them as Markdown; they are kept whole when chunking |
| `ocr` (`pymupdf_text`) | off | Run OCR on pages with no text layer; needs Tesseract installed |

## Chunk

Splits text into passages. A rebuild stage.

| Type | Behaviour |
| --- | --- |
| `fixed` | Cuts every N characters or tokens, ignoring boundaries |
| `recursive` | Splits on paragraphs, then lines, sentences and words until pieces fit |
| `sentence` | Packs whole sentences; never cuts mid-sentence unless one is too long |
| `semantic` | Splits where meaning shifts between neighbouring sentences, using a local model |
| `structure_aware` (default) | One section per heading; long sections split recursively. Best for docs and manuals |

| Option | Default | Meaning |
| --- | --- | --- |
| `size` | 1000 | Target chunk size (the maximum for `semantic`) |
| `overlap` | 150 | How much of the previous chunk repeats at the start of the next |
| `unit` | `chars` | `chars`, or approximate `tokens` |
| `min_chunk_size` | 0 (100 for `semantic`) | Smaller chunks merge into their neighbour |
| `separators` (`recursive`) | paragraph, line, sentence, space | Tried in order |
| `heading_depth` (`structure_aware`) | 3 | Start a new section at headings up to this level |
| `include_heading_in_text` (`structure_aware`) | on | Prefix each chunk with its heading path so it carries its context |
| `breakpoint_percentile` (`semantic`) | 90 | Split where neighbouring sentences differ more than this share of pairs; higher gives fewer, larger chunks |
| `model` (`semantic`) | `bge-small-en-v1.5` | Local model that compares neighbouring sentences |

## Embed

Turns each passage into a vector. A rebuild stage, except where noted.

| Type | Behaviour |
| --- | --- |
| `fastembed` (default) | A local model on your CPU: free, private and deterministic; downloaded once |
| `api` | Hosted Gemini or NVIDIA embeddings, using your quota; slower to build |

| Option | Default | Meaning |
| --- | --- | --- |
| `model` | `BAAI/bge-small-en-v1.5` | The embedding model (see below) |
| `normalize` | on | Scale vectors to unit length, so cosine equals dot product |
| `doc_prefix` | model default | Text prepended to every chunk before embedding |
| `query_prefix` | model default | Text prepended to questions (**instant**) |
| `batch_size` | 32 (50 for `api`) | Texts embedded at once (**instant**) |
| `provider` (`api`) | `gemini` | `gemini` or `nvidia` |

Local models include `bge-small-en-v1.5` (small and fast), `all-MiniLM-L6-v2`, `snowflake-arctic-embed-s`, `bge-base-en-v1.5` (better quality), `nomic-embed-text-v1.5`, `mxbai-embed-large-v1`, `bge-m3`, `e5-large-v2` and `jina-embeddings-v2-base-en`. Larger models are slower and need more memory. Use a [sweep](/docs/sweeps) to compare them on your documents.

## Vector store

Stores and searches the vectors. Switching store type never re-embeds, because vectors are cached.

| Type | Behaviour |
| --- | --- |
| `numpy` | Brute-force and exact; the reference baseline |
| `faiss` (default) | Meta's library; Flat is exact, IVF and HNSW trade accuracy for speed |
| `chroma` | Embedded Chroma with an approximate HNSW index |
| `lancedb` | Embedded columnar database; exact scan by default, optional IVF, PQ or HNSW |
| `qdrant` | Qdrant's embedded local mode; searches exactly locally |

All stores take `metric`: `cosine` (default, right for almost every text model), `dot` or `l2`.

| Store | Option | Default | Meaning |
| --- | --- | --- | --- |
| FAISS | `index_type` | `Flat` | `Flat` exact, `IVFFlat` clusters, `HNSW` graph |
| FAISS | `nlist`, `nprobe` | 64, 8 | IVF clusters, and clusters searched (**instant**) |
| FAISS | `hnsw_m`, `ef_construction`, `ef_search` | 32, 200, 64 | HNSW links, build effort, search effort (**instant**) |
| Chroma | `hnsw_m`, `ef_construction`, `ef_search` | 16, 100, 100 | As above; search effort is **instant** |
| LanceDB | `index_type` | `none` | `none`, `IVF_FLAT`, `IVF_PQ` or `IVF_HNSW_SQ` |
| LanceDB | `num_partitions`, `num_sub_vectors` | 16, 16 | IVF partitions; PQ sub-vectors |
| LanceDB | `nprobes`, `refine_factor`, `ef` | 20, 0, 64 | Search effort (**instant**) |
| Qdrant | `on_disk_payload` | on | Store payloads on disk |

Start with exact search (FAISS Flat) for correctness. Move to HNSW when you have tens of thousands of chunks and need speed.

## Cache

Checked before retrieval. Instant.

| Type | Behaviour |
| --- | --- |
| `none` (default) | Answer every question from scratch |
| `semantic` | Reuse the answer to a near-identical earlier question, with no retrieval and no model call |

Semantic cache options: `threshold` (0.95, cosine similarity needed), `ttl_hours` (168), `max_entries` (2000). Numbers and code identifiers must match exactly, a hit needs the same configuration and documents, and truncated or not-grounded answers are never cached. The stage shows stats and a **Clear** button.

## Compute

Before retrieval. `none` (default) or `attested`, which routes numeric questions to a computation on the [Data tab](/docs/data). Option `on_fail`: `documents` (answer from the documents with a warning) or `refuse`.

## Retrieve

Finds candidate passages. All options are **instant**.

| Type | Search paths |
| --- | --- |
| `fused` (default) | Dense, keyword and exact, combined. Best default; adds exact matching for error messages and symbols |
| `hybrid` | Dense and keyword |
| `dense` | Vectors only |
| `keyword` | BM25 full text only; no embeddings at query time |
| `agentic` | An LLM planner searches in steps, reads passages and keeps the ones that answer |

| Option | Default | Meaning |
| --- | --- | --- |
| `top_k` | 8 | Chunks passed on (before reranking, if on) |
| `fusion` | `rrf` | `rrf` (rank-based) or `weighted` (score-based) |
| `rrf_k` | 60 | RRF constant; higher flattens the advantage of top ranks |
| `dense_weight`, `keyword_weight`, `exact_weight` | 1.0, 1.0, 1.5 | How much each path counts |
| `candidates` | 40 | Results each path contributes before fusion |
| `min_score` | 0 | Drop dense results below this similarity |
| `pin_definitions` | on | Put sections whose heading exactly names the symbol or error you asked about first |
| `mmr`, `mmr_lambda` | off, 0.7 | Diversify results; 1 is pure relevance, 0 pure diversity |
| `query_expansion` | `none` | `multi_query` (rewrites), `hyde` (a hypothetical answer, dense only) or `decompose` (split a multi-part question) |
| `expansion_queries` | 3 | Rewrites to search with, or the most sub-questions |
| `context_window` | 0 | Add this many neighbouring chunks (same document) around each result |
| `okf_policy` | off | Leave out documents past `stale_after`, halve the score of deprecated ones, prefer better-verified sources |
| `adapter` | none | A query-side embedding adapter trained in Evaluate |

Query expansion costs one extra model call per question. `decompose` searches each sub-question separately and interleaves the results so every part gets evidence.

Agentic options: `search_mode` (the retriever each search uses, `fused`), `max_steps` (3, the most planner calls per question), `per_search_k` (5) and `offload` (off: show the agent short references instead of full passages, so it reads only what it opens). It costs several model calls per question; check the "vs hybrid + rerank" column in a [sweep](/docs/sweeps) to see whether it pays for itself.

## Rerank

| Type | Behaviour |
| --- | --- |
| `none` (default) | Keep the retrieval order |
| `cross_encoder` | Re-scores each question and chunk pair locally; usually a large precision gain for a little latency |

Options: `model` (`ms-marco-MiniLM-L-6-v2` by default; larger and Jina or BGE rerankers are available) and `top_n` (5), the chunks that survive and go to the prompt. Instant.

## Prompt

Builds the model's context. All options are **instant**.

| Type | Behaviour |
| --- | --- |
| `cited_qa` (default) | A citation on every claim |
| `concise` | One to three sentences, still cited |
| `detailed` | Longer, structured answers |
| `custom` | Your own system prompt and message template (`user_template` must contain `{context}` and `{question}`) |

| Option | Default | Meaning |
| --- | --- | --- |
| `max_context_tokens` | 4000 | Chunks are added in rank order until this budget is reached |
| `say_dont_know` | on | Refuse to answer beyond the sources |
| `source_labels` | on | Show each source's document, page and section to the model |
| `injection_guard` | `data_rule` | `none`, `data_rule` or `delimited` (see [Advanced evaluation](/docs/advanced-evaluation)) |
| `extra_instructions`, `examples` | empty | Appended instructions and few-shot examples; written by prompt optimisation |

## Generate

The model that writes the answer: any connected [provider](/docs/providers). Instant.

| Option | Default | Meaning |
| --- | --- | --- |
| `model` | provider default | The model |
| `temperature` | 0.2 | Lower is focused and repeatable; higher is more varied |
| `top_p` | 1.0 | Nucleus sampling; lower is more focused |
| `max_tokens` | 4096 | Upper limit on the reply, including any hidden reasoning |
| `reasoning_effort` | `none` (`default` for NVIDIA) | `default`, `none`, `low`, `medium` or `high`; thinking tokens count against `max_tokens` |

## Verify

Runs after generation. Instant.

| Type | Behaviour |
| --- | --- |
| `none` (default) | Return the answer as generated |
| `grounding_check` | An extra model call grades every claim and citation against the sources |
| `execution_check` | For code answers: run the Python in a Docker sandbox against tests |

| Option | Default | Meaning |
| --- | --- | --- |
| `validate_output` (all types) | off | Remove URLs, emails and phone numbers that appear in no source |
| `on_fail` (`grounding_check`) | `retry_with_more_context` | Retry with twice the results and budget, or only `flag` |
| `max_retries` (`grounding_check`) | 1 | Each retry is another retrieval, answer and check |
| `max_steps` (`execution_check`) | 3 | Most attempts to fix failing code |
| `allow_generated_tests` | on | Let the model write tests when none are available (labelled weaker evidence) |
| `timeout_s` | 10 | Time limit per run |

The code check needs Docker running; without it the check is skipped and never run locally. `SANDBOX_IMAGE` (default `python:3.12-slim`) selects the image.
