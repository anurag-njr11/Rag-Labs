# Sweeps

A sweep scores many configurations on the same eval set and shows which ones win on quality and which on cost, so you choose from evidence.

## Run a sweep

1. Open **Evaluate**, then **Sweeps**.
2. Click values on one or more axes. Axes are chunk size, chunking strategy, local embedding model, retriever (including agentic), query expansion, context window, top-k, reranker and the grounding check. Values marked *(current)* are what the base version uses; include them so your current setup is part of the comparison.
3. Pick the **base version** (the active one by default). Everything you do not vary comes from it.
4. Check the count next to **Run sweep**. A grid can have at most 48 configurations; untick values to reduce it.
5. Click **Run sweep**. Click **Stop** to end it early; results that finished are kept.

Instant axes (retriever, top-k, reranker) reuse one index. Rebuild axes (chunking, embedding model) build one index per value, with parsing and embeddings taken from cache wherever possible. A new embedding model downloads on first use. When chunk size varies, the overlap keeps the base version's overlap-to-size ratio.

## Presets

Presets fill in a grid in one click: **Agentic vs hybrid + rerank** (hybrid against agentic retrieval, with the reranker off and on), **Grounding check on vs off** (which also turns on Auto-Optimize, since only answer grading separates these), and the config-prior preset (**Verify the prediction for corpora like yours**, described below). Use them as a starting point and adjust.

## Read the leaderboard

- **The blue line** says what the best configuration gains over your current one, and whether a cheaper configuration is nearly as good.
- **The chart** plots quality (MRR) against cost (query tokens per question: the answer context plus any retrieval-side LLM calls). A star marks the **Pareto frontier**: configurations no other one beats on both axes. Choose from the frontier.
- **Columns** show Hit@k, MRR, tokens per question, p50 latency, the share of questions whose passage still fits the prompt budget, and for agentic configurations a "vs hybrid + rerank" comparison of MRR, token multiple and latency multiple.
- **Promote** creates a new version from that row and makes it active, so the Playground and API use it immediately.

A row that "couldn't run" is explained in the list under the leaderboard. Usually the combination is invalid (for example overlap not smaller than chunk size) or a model failed to download. The other rows are still valid.

## Auto-Optimize

Turn on **Auto-Optimize** to also grade answers for the best quarter of configurations (at most 5) once retrieval scoring finishes. An **Answers** column appears. If a graded configuration's answer score is within noise of the leader's, it is re-judged twice more and the median verdict is kept. If the confidence ranges still overlap, the blue line says they are *tied within noise*; do not pick a winner on that column alone. Cells that tie on retrieval are graded together, because only answer grading tells them apart. When the code check is used, execution-verified correctness ranks configurations before MRR.

## Embedding candidates

Embedding models are listed best first by their self-reported MTEB retrieval score, shown on each chip (a dash where the model card reports none). **MTEB top 3** picks the three highest plus your current model. A public benchmark is a starting point, not a verdict, which is why the sweep measures candidates on your documents.

## Cost projection

Above the leaderboard, enter queries per month and your model's price per 1M input and output tokens. A **$ per month** column appears. It uses each configuration's context tokens, about 150 tokens of prompt overhead, and the average answer length from your chat history.

## Config prior

The **config prior** predicts settings for your corpus from the sweeps that won on similar corpora on this installation, with a stated confidence (agreement, amount of evidence and similarity). With no history it falls back to a rule-based recommendation and labels it as such. The preset sets up a sweep that verifies the prediction against your current settings, so you test it rather than trust it.

## Tips

- Vary two or three axes at once, not six. The grid grows fast and you learn less from a huge table.
- Sweeps use the eval set you have, so a small set can only separate large differences. See [Evaluate](/docs/evaluate).
- Retrieval scoring in a sweep uses no LLM calls, except where the configuration itself makes them: query expansion (one call per question) and the agentic retriever (a few planner calls). Auto-Optimize adds answer generation and grading.
