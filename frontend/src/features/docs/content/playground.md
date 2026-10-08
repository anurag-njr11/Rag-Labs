# Playground

The Playground is where you ask questions and see exactly how each answer was produced: what was retrieved, what reached the model, what was cited and what every step cost.

## Asking a question

Type a question, or paste an error message, and press Enter. The answer streams in token by token. Citations appear as `[1]`, `[2]` markers; click one to jump to its source in the inspector, or use **Inspect sources** under the answer. Click **Stop** to cancel a long answer. If the answer was cut off by the token limit it is marked **Incomplete**.

Empty chats suggest questions to try: from your eval set, and from sections of your documents. **Recent runs** lists earlier questions, including calls made through the API, so you can reopen any of them.

The Playground answers with the **active version**. Its model and vector store are shown above the chat.

> **Note** If you changed a rebuild setting, the first question rebuilds the index before answering. A status line tells you it is updating.

## The inspector

Open the inspector to see how the answer was assembled. Each retrieved passage shows:

| Field | Meaning |
| --- | --- |
| Rank and score | Its position after fusion and reranking, and its score |
| Found by | The search paths that returned it: **dense** (meaning), **keyword** (BM25) or **exact** (verbatim symbol or error lookup) |
| Document, page, heading | Where it came from, with the section breadcrumb |
| In context | Whether it fit in the prompt's token budget; passages that did not are shown as dropped |
| Cited | Whether the answer cited it, with the supporting spans highlighted in the passage |

Pinned passages (sections whose heading matches your question) are marked.

## The trace

The trace lists every step with its latency, tokens and cost, and draws the steps as a **timeline** so that parallel retrieval paths appear side by side. Typical steps are the embedding of the question, each search path, fusion, reranking, prompt building, generation, and any optional step you enabled (query expansion, cache lookup, agent searches, grounding check).

Use it to find the bottleneck. If the embedding step is slow, switch to a local embedding model. If generation dominates, lower the maximum tokens or pick a faster model. If dense search is slow, consider an approximate index.

Totals show end-to-end latency, input and output tokens, and the list-price cost of the question. A step whose model has no published price shows a dash rather than $0.

## Reading a bad answer

Work backwards through three questions:

1. **Was the right passage retrieved?** If it is not in the list at all, retrieval failed: try a stronger embedding model, a higher `top_k`, different chunking or the `fused` retriever.
2. **Did it reach the prompt?** If it is retrieved but marked dropped, the token budget cut it: raise **Max context tokens** or add a reranker so fewer, better passages are sent.
3. **Was it in the prompt but ignored?** Then generation failed: lower the temperature, tighten the prompt, or use a stronger model.

Instead of checking one question at a time, [evaluate](/docs/evaluate) the version; the diagnoses classify every miss this way.

## Optional behaviours you may see

- **Cache hit.** With the semantic cache enabled, a near-identical earlier question is answered with no retrieval and no model call. The trace shows the hit. Numbers and code identifiers must match exactly, so "top 10" does not reuse the answer for "top 15".
- **Grounding check.** With the Verify stage enabled, each claim and each citation is checked against the sources. An unsupported claim flags the answer or triggers a retry with more context; the result is shown under the answer.
- **Code check.** For code answers, the Verify stage can run the answer's Python in a sandbox and show whether it passed. See [Advanced evaluation](/docs/advanced-evaluation) and the [pipeline reference](/docs/pipeline-reference).
- **Attested computation.** For numeric questions answered from a table, the answer comes with a receipt of the query and the checks it passed. See [Computations](/docs/data).
- **Output validation.** URLs, emails and phone numbers that appear in no source are removed from the answer.

## History and the production loop

Every question is stored as a run with its retrieved passages, trace and cost, and is labelled by where it came from: the Playground or the API. [Corpus Health](/docs/health) uses these real questions to find gaps in your documents.
