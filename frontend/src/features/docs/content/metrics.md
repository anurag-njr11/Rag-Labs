# Metrics

Definitions of everything RAGLabs measures, so a number on a scorecard is never a mystery.

## Retrieval metrics

Computed exactly and repeatably, with no LLM involved. Each question has one expected passage, identified by its evidence quote.

| Metric | Definition |
| --- | --- |
| **Hit@k** | The share of questions where a passage containing the evidence is among the first k results. Hit@1 and Hit@3 are shown too. The k in Hit@k is the number that reaches the prompt: `top_k`, or the reranker's `top_n` when reranking |
| **MRR** | Mean reciprocal rank: the average of 1 divided by the rank of the first hit (0 when none). 1.0 means always first |
| **nDCG@k** | A rank-weighted hit score. With one relevant passage per question it equals 1 divided by log2(rank + 1) for a hit in the top k, averaged over questions |
| **Context hit** | The share of questions whose evidence survives the prompt's context budget |
| **Retrieval p50, p95** | Median and 95th percentile time to retrieve and rerank one question. A cached model step (query expansion, agent run) is counted at the time it really takes |
| **Query tokens** | Average tokens sent to models per question: the answer context plus retrieval-side calls (query expansion, agent planning). The cost axis of the sweep chart |
| **Index size** | Chunks, vectors and bytes of the index that was scored |
| **Cost per 1k queries** | List-price cost of the retrieval stage (query expansion), or the whole pipeline when answers were graded; unknown when a model has no published price |

### What counts as a hit

A passage is a hit when it contains the question's evidence, verbatim or with nearly all of its words, **and** comes from the question's source document. Because the label is a quote and not a chunk, the same eval set scores any chunking. For an external RAG, the document check compares file names when the system names a source, and is skipped when it does not. See [Evaluate your own RAG](/docs/your-rag).

### Confidence intervals

Hit rates carry 95% **Wilson intervals**, which behave sensibly with few questions and at 0% or 100%. MRR carries a normal-approximation interval. When two runs' intervals overlap, RAGLabs shows "tie" rather than an arrow, because the difference is within noise. With 20 to 30 questions, differences under about 10 points are often noise.

## Answer metrics

Computed only when **Also grade answers** is on. A judge model reads the question, the expected answer, the required facts, the system's answer and its sources, and returns verdicts. Verdicts are judgements, so a re-run can differ by a question or two.

| Metric | Definition |
| --- | --- |
| **Answers correct** | The share of answers graded fully correct against the expected answer, with a 95% interval; partly correct answers are counted separately |
| **Grounded** | The share of answers whose every claim is supported by the sources sent |
| **On-topic** | The share of answers the judge found relevant to the question |
| **Context recall** | The share of required facts that the retrieved passages support |
| **Context precision** | Rank-weighted share of retrieved passages that were relevant: the mean of precision at each relevant position, so relevant passages ranked first score higher |
| **Answer p50, p95** | Time to write the answer, including any grounding check and retries |
| **Execution-verified** | For questions with tests: the share whose answer's code passed them in the sandbox, with a 95% interval |
| **Grounding check pass rate** | The share of answers the grounding check passed, and how many it retried |

## Diagnoses

Every miss gets one diagnosis, most upstream first.

| Diagnosis | Meaning |
| --- | --- |
| `not_retrieved` | The evidence is not in the top 50 even with a deep search |
| `ranked_below_k` | Found deeper than the cut-off |
| `dropped_by_rerank` | Retrieved, then removed by the reranker |
| `dropped_by_budget` | Retrieved and kept, but cut by the prompt's context budget |
| `incorrect_format` | The evidence reached the prompt but the answer broke the citation contract |
| `incomplete_answer` | The evidence reached the prompt but required facts are missing |
| `wrong_specificity` | The evidence reached the prompt but the answer is too vague or too verbose |
| `failed_to_extract` | The evidence reached the prompt and nothing else explains the wrong answer |

The last four need answer grading. See [Evaluate](/docs/evaluate) for the fixes.

## Sweep and cost columns

- **Pareto frontier**: configurations that no other configuration beats on both quality (MRR) and cost (query tokens).
- **vs hybrid + rerank**: for a configuration, the MRR difference against hybrid retrieval with a reranker, and the token and latency multiples.
- **$ per month**: queries per month times each configuration's context tokens, about 150 tokens of prompt overhead and your average answer length, at the prices you enter.

## Corpus Health numbers

- **Answered by the docs**: the share of real questions graded covered (partial counts separately).
- **Gap topics**: groups of unanswered questions, sized by how many questions fall in them.
- **Duplicates**: passage pairs with vector similarity of 0.97 or more.

See [Corpus Health](/docs/health).
