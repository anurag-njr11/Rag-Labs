# Corpus Health

The Health tab looks at the documents themselves rather than the configuration. Most bad answers come from documentation that is missing, contradictory or out of date, and no pipeline setting can fix that.

## What it checks

| Section | What it means | How it is found |
| --- | --- | --- |
| Answered by the docs | The share of **real** questions your documents can fully answer | Each question is searched with the version's retriever; your Generate model then grades the passages that would reach the prompt as *covered*, *partial* or *missing* |
| Content backlog | Questions that are not fully answered, grouped into topics, biggest first | Similar questions are grouped; each topic is named after what the documentation would need to add |
| Retrieval misses | Questions your documents do answer, but the pipeline did not find the passage | Each unanswered question is searched again much deeper (top 15) and re-graded; if that answers it, it is a retrieval miss and not a content gap |
| Stale documents | Documents marked deprecated, past their stale-after date, or not modified for longer than the threshold (365 days by default) | From each document's metadata and last-modified date; documents with neither cannot be checked |
| Contradictions | Passages in different documents that state conflicting facts | The most similar passage pairs across documents (up to 30) are checked by the model |
| Duplicate content | Near-identical passages in different documents | Vector similarity of 0.97 or more; no model involved |
| Unused content | Documents and chunks that none of the questions ever pulled into the prompt | Counted from the same searches |

## Run a check

1. Ask real questions in the Playground or through the API. They are collected automatically and counted on the Health tab.
2. Optionally paste more questions, one per line, into **Real user questions**. Support tickets and search logs are ideal.
3. Optionally change **Flag documents not modified in N days**, and choose whether to count questions from the Playground and API, or API traffic only.
4. Click **Check corpus health**. Progress shows *Search each question*, *Check answers against the docs*, *Re-check gaps with a deeper search*, *Find overlapping passages* and *Check for contradictions*.
5. Work through the **Content backlog** from the top. Expand a topic to see its questions and the closest passage that was found.
6. Click **Download report (.md)** to hand the backlog to whoever owns the documentation.

A report uses up to 200 questions. It costs about one LLM call per 5 questions, one more per 5 unanswered questions for the deeper re-check, and up to 6 for contradictions.

## Gaps versus retrieval misses

- A **backlog topic** means even a deep search found nothing that answers it: **write the content**.
- A **retrieval miss** means the content exists but the pipeline ranks it too low: run a [sweep](/docs/sweeps) or raise `top_k`.

## The production loop

Every answer records whether it came from the Playground or the API. Switch on **Re-run automatically** to have Health re-check after every N new real questions (checked after each answer; there is no scheduler). Each report then shows its trend against the previous one: the change in coverage, gaps resolved, questions no longer answered and new gaps. Use **API traffic only** to look at production behaviour without your own testing.

## Tips

- **Use real questions.** Eval-set questions are written from your documents, so by construction they cannot reveal missing content. That is why Health uses real ones.
- **Off-topic questions show up too** ("What is the capital of France?"). Ignore topics that are not yours to document.
- **"Unused" needs volume.** With fewer than about 30 questions, unused mostly means nobody has asked yet.
- If a check reports *couldn't be graded*, one batch of grading calls failed, often a rate limit. Run the check again.
