# Evaluate

The Evaluate tab answers "is this configuration any good?" with numbers instead of a few hand-picked questions. You do not write or label anything.

## How it works

1. **Sample.** Passages are picked evenly from every document in the index. Very short passages and tables are skipped.
2. **Write questions.** Your configured LLM (the Generate stage's provider and model) writes one question per passage, with the answer, an exact quote from the passage as evidence, and the one to four facts a complete answer must state.
3. **Filter.** A question is dropped if its quote is not really in the passage, or if the model can answer it with no documents at all. That second kind tests the model's memory, not your retrieval.
4. **Score.** Each remaining question runs through a version's Retrieve and Rerank stages. The score is where the first passage containing the evidence lands. No LLM is involved, so scoring is free and gives the same numbers every time.

## Generate an eval set

1. Open **Evaluate** on a project with documents.
2. Choose a size (10, 20, 30 or 50 questions; 30 is a good default) and click **Generate eval set**. Progress shows *Write questions* then *Filter generic questions*. If the index is out of date it is rebuilt first.
3. Review the set on the eval-set card. Badges show how many questions were **kept** and how many were rejected as **too generic** or for **bad evidence**. Expand **Questions** to see each answer, its evidence and what the model said without documents, and **Rejected by the filter** to see what was dropped and why.

Generating 30 questions takes about 14 LLM calls, and document passages are sent to your provider.

## Run an evaluation

Under **Retrieval quality**, pick a version (the active one by default) and click **Run evaluation**. Turn on **Also grade answers** to write each answer with the version's prompt and model and have a judge model grade it; that costs about 1.2 LLM calls per question. Choose who judges with the **Judge model** menu at the top: by default the version's own model, but a different model avoids a model grading its own answers.

Each run adds a row to **Run history**. Arrows show the change from the previous run in percentage points, and "≈ tie" appears when the 95% intervals overlap so the difference is not significant. A run is marked *edited since this run* if the eval set changed after it.

## Reading the results

The scorecard opens with a verdict, then the metrics. With fewer than 100 questions it says "Small set" rather than praising the score, because a small sample cannot tell close configurations apart.

| Metric | Meaning | Good sign |
| --- | --- | --- |
| Hit@1 | Share of questions where the right passage was ranked first | High |
| Hit@3 | Right passage in the top 3 | High |
| Hit@k | Right passage in the final k results that reach the prompt (k is `top_k`, or the reranker's `top_n` when reranking) | Close to 100% |
| MRR | Mean of 1 divided by the rank of the first hit; 1.0 means always first | Near 1.0 |
| nDCG@k | Rank-weighted hit score | Near 1.0 |
| Retrieval p50 and p95 | Median and slow-tail time to retrieve and rerank one question | Low |
| Cost per 1k queries | List-price LLM cost; only the retrieval stage unless answers are graded | Low |
| Index size | Chunks, vectors and bytes of the index that was scored | Small for the same quality |

The metrics in the first four rows come with 95% confidence intervals, so you can see when two numbers are really different. See [Metrics](/docs/metrics) for the full definitions, including the answer metrics.

> **Tip** Compare, do not brag. Generated questions often reuse the document's wording, so absolute scores run a little optimistic. The value is in comparing configurations on the same eval set. With 20 to 30 questions a difference under about 10 points may be noise; use 50 for close calls.

## Why a question missed

Every miss gets one diagnosis, most upstream cause first, and a suggested fix.

| Diagnosis | What happened | Try |
| --- | --- | --- |
| Not retrieved | The passage is not in the top 50 at all | A different retriever (for example `fused`), a better embedding model, or different chunking |
| Ranked below top-k | Found deeper in the ranking than your cut-off | Raise `top_k`, or add a reranker |
| Dropped by reranker | Retrieved, then cut by the reranker | Raise the reranker's **Keep top N** |
| Cut by context budget | Retrieved, but did not fit in the prompt | Raise **Max context tokens** or lower `top_k` |
| Broke the citation format | The passage was there but the answer cited wrongly or not at all | State the citation rule in the prompt, or use a cited prompt style |
| Incomplete answer | The answer left out required facts | The Detailed prompt style or query decomposition |
| Wrong level of detail | The judge found the answer too vague or too verbose | Tune the prompt style |
| Wrong answer despite context | The passage reached the model but the answer was wrong | Another prompt style or model, or fewer and cleaner passages |

The last four appear only on runs that grade answers. Use **Only misses** in the per-question table to list just the failures, and expand a question to see the expected answer, the evidence and what came back.

### Apply fix

Under *Why questions failed*, three causes have an **Apply fix** button:

| Cause | What Apply changes |
| --- | --- |
| Ranked below top-k | Raises `top_k` to the deepest rank the missed passages were found at |
| Dropped by reranker | Raises the reranker's Keep top N by 3 (up to `top_k`) |
| Cut by context budget | Raises Max context tokens by 50% |

A dialog shows the exact change first. Saving creates a new active version, which is scored automatically so the result appears in Run history with arrows. The other causes have no single-setting fix: run a [sweep](/docs/sweeps), or try another prompt style or model.

## Edit the eval set

Click **Edit questions** on the eval-set card to:

- **Add** your own question: give the expected answer, pick the document, and paste a sentence from it word for word as evidence. It is rejected if that sentence is not in the document, because it could never be scored.
- **Edit** a question, answer, evidence or its required facts, **drop** a bad question from scoring or **restore** a rejected one, or **delete** it.
- **Export CSV** to review in a spreadsheet, or **Import CSV** with columns `question`, `gold_answer` (or `answer`), `evidence` and `document` (the file name), and optionally `facets` (required facts separated by `|`) and `tests`. Rows that cannot be used are listed with the reason.

Edits apply to the next run and bump the set's revision. Earlier runs keep the questions they were scored on, so re-run before comparing.

## Automatic re-scoring

Once a project has an eval set, every version you save on the Configure tab is scored on the newest set automatically. The save message says so, and the new run appears in Run history. Versions saved in the create wizard are not auto-scored.

## Other tools in this tab

| View | What it is for |
| --- | --- |
| Retrieval quality | This page: score one version at a time |
| [Sweeps](/docs/sweeps) | Score many configurations and see the quality-versus-cost frontier |
| [Your RAG](/docs/your-rag) | Score a RAG system that runs elsewhere |
| [Advanced evaluation](/docs/advanced-evaluation) | Embedding adapter, prompt optimisation and injection resistance |

## Tips

- **Instant changes are cheap to test.** Retriever type, `top_k`, weights and the reranker need no rebuild. Rebuild changes such as chunking or the embedding model build the new index on the first run.
- **Regenerate after big document changes.** Questions whose source document was deleted always miss, and show a dash as their source.
- **Retrieval metrics are exact and repeatable. Answer grades are judgements** from a model, so a re-run can differ by a question or two. Lead with the retrieval numbers.
- **Privacy.** Retrieval scoring runs entirely on your machine. Question generation and answer grading send passages, questions and answers to your provider.
