# RAG Builder — Presentation Q&A Prep

Sep 24, 2026 · @Ace

## Read first

Don't quote "60% of problems happen in chunking" or "80% of RAG failures start in ingestion". Neither comes from a research paper: the 80% figure traces to blog posts ([example](https://dev.to/ragprep/80-of-rag-failures-start-here-and-its-not-the-llm-11lp)). A judge who asks for the source would catch it.

Every claim below has a source you can name. Each answer starts with a line to say, then the evidence, then likely follow-ups.

## Q1. What problem are we solving?

**Say:** "Teams choose chunking, embedding model, retriever and reranker by guesswork. Research shows each choice measurably changes quality, but teams only find out from users after launch."

**Evidence:**

- **[Barnett et al., 2024, "Seven Failure Points When Engineering a RAG System"](https://arxiv.org/abs/2401.05856)** (CAIN '24).
  - Three real deployments (research, education, biomedical) produced 7 failure points.
  - 3 of the 7 happen before the LLM writes anything: the content is missing, the right document is ranked too low, or it's retrieved but never reaches the prompt.
  - Their conclusions are our problem statement: *"validation of a RAG system is only feasible during operation"* and *"the robustness of a RAG system evolves rather than designed in."*
- **[Chroma technical report, 2024](https://www.trychroma.com/research/evaluating-chunking):** the chunking strategy alone changes retrieval recall by **up to 9 points**.
- **Infosys practitioner report** (from our research notes; not peer-reviewed): about **70%** of apparent RAG errors traced back to outdated or incorrect documentation.

**Likely follow-up: "So is it the chunking or the documents?"** Both, and neither can be seen without measurement. Chunking moves recall by points; a missing document caps the score at zero. Our evaluation separates the two: "not retrieved" versus "ranked too low".

## Q2. What's the tech stack, and why not LangChain?

**Say:** "We're building a measurement tool, so we have to see and control every step. A framework that hides calls would hide exactly what we measure."

| Layer | What we use |
| --- | --- |
| Backend | FastAPI (Python), async throughout |
| Storage | SQLite; its built-in full-text search (BM25) does keyword search |
| Vector stores | NumPy, FAISS, Chroma, Qdrant, LanceDB — all embedded, no server |
| Embeddings and reranking | fastembed models running locally on CPU; cross-encoder rerankers |
| Document parsing | pymupdf4llm, pymupdf, pypdf; python-docx; trafilatura for HTML |
| LLMs | Gemini and NVIDIA through one OpenAI-compatible client |
| Frontend | React 19, TypeScript, Vite, Tailwind, TanStack Query; streaming over SSE |

**Why not LangChain:**

1. **Hidden calls.** Infosys found that LangChain's `ConversationalRetrievalChain` quietly made **two LLM calls per question**, doubling cost and latency without anyone noticing. We trace every step's latency and tokens.
2. **Blocking calls.** In the same report, responses reached **180 seconds at 50 concurrent users**; switching to async brought them to about 9 seconds.
3. **Reproducibility.** The same config must give the same ranking every time. We control tie-breaking and exact search ourselves.
4. **Small enough to own.** Our whole retrieval orchestrator is about 200 lines. Each pattern is 50–150 lines of our own code.

**Honest concession:** LangChain is faster for prototyping and has more integrations. We traded breadth for control.

## Q3. Who are the competitors, and what do they lack?

**Say:** "Builders help you make a pipeline, evaluation libraries score it, and optimizers tune it offline. We put checkable, repeatable measurement inside the builder, and tell you why each miss happened."

| Group | Examples | Gap |
| --- | --- | --- |
| Visual builders | LangFlow, Flowise, Dify, RAGFlow | Focused on building pipelines; measuring them isn't the core |
| Evaluation libraries | RAGAS, TruLens, DeepEval, LangSmith | A separate tool you wire in yourself; mostly LLM-graded scores |
| Automatic optimizers (closest) | [AutoRAG](https://arxiv.org/abs/2410.20878), [KruxAI RAGBuilder](https://github.com/KruxAI/ragbuilder) | Offline tuning scripts for ML engineers |

**Don't claim nobody automates RAG evaluation.**

- AutoRAG and KruxAI RAGBuilder both tune configs against synthetic questions.
- RAGAS also generates test sets ([docs](https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/)).
- KruxAI's product is also called "RAGBuilder" — a naming risk for us.

**What's different about us today:**

- **No-documents filter:** a generated question is dropped if a model can answer it without the documents. We show the rejected ones.
- **Answers tied to exact quotes:** the same test set can compare configs with *different chunking*.
- **Diagnosis per miss:** each miss says why it happened and suggests a fix.
- **Built into the builder:** it sits next to the playground and version history, not in a separate script.

## Q4. How is RAG evaluated today, and why does it fall short?

**Say:** "Every current method is too small to trust, too expensive to keep up, too noisy to repeat, or measures someone else's data."

| Method | Why it falls short |
| --- | --- |
| Trying a few questions by hand | Too few questions, biased toward ones you know work, not repeatable |
| Hand-written test sets | Most reliable, but expensive and stale once documents change — so few teams build them |
| An LLM as grader (RAGAS, TruLens) | Documented bias toward the first answer shown, longer answers and its own output ([Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685)); scores vary between runs; every run costs money |
| Public leaderboards (MTEB, BEIR) | Someone else's data: [BEIR](https://arxiv.org/abs/2104.08663) showed rankings change on new domains, and plain BM25 keyword search is a strong baseline |
| One end-to-end answer score | A low score doesn't say which of the 7 failure points to fix |

The result is Barnett's conclusion: without a cheap, trustworthy test, validation only happens in production.

## Q5. What's our solution, and why does it work?

**Say:** "We turn 'you can only validate in production' into a check you run before shipping, with no labelling."

```mermaid
flowchart LR
  A[Sample chunks<br/>from your docs] --> B[LLM writes question,<br/>answer, exact quote]
  B --> C[Filter: quote must exist;<br/>drop if answerable without docs]
  C --> D[Run each question<br/>through a version]
  D --> E[Rank of first chunk<br/>containing the quote]
  E --> F[Hit@1, Hit@k, MRR<br/>+ diagnosis per miss]
```

Each step removes a weakness of the methods in Q4.

**Why it works:**

1. **Your documents, not a benchmark.** Questions come from the user's own corpus.
2. **Checkable answers.** Every answer is tied to an exact quote we verify exists in the source; if it doesn't, the question is rejected.
3. **Tests retrieval, not memory.** The no-documents filter drops questions a model answers from general knowledge.
4. **Repeatable and free.** Scoring is plain arithmetic, with no LLM grader. The same run gives the same number and takes about a second per question.
5. **Any two versions compare fairly.** Answers don't depend on chunking.
6. **Tells you what to fix.** Each miss is labelled "not retrieved", "ranked below top-k" or "dropped by reranker" — Barnett's failure points 2 and 3 — with a suggested fix.

**Live result (19 questions, same test set):**

| Version | Setup | Hit@1 | Hit@8 | MRR |
| --- | --- | --- | --- | --- |
| v4 | Hybrid retrieval + cross-encoder reranker | 79% | 100% | 0.85 |
| v1 | Hybrid retrieval, no reranker | 58% | 89% | 0.71 |

The filter rejected 1 of 20 generated questions as answerable without the documents.

**State the limits before you're asked:**

- Generated questions tend to reuse words from the source, so absolute scores run optimistic. Use the tool to *compare configs*.
- With about 20 questions, differences under 10 points are noise.
- It measures retrieval, not answer quality. Scoring answers is the next layer.

**Strongest closing line (needs prep):** hand-check 20 questions and say "the automatic grading agreed with a human on X of 20."

- [ ] Run the same version twice and confirm identical scores
- [ ] Run a deliberately bad config (top-k 1 or keyword-only) and confirm the score drops
- [ ] Hand-check 20 questions and record the agreement number

## Hard questions about the evaluation

**Q6. "Isn't it circular to have an LLM write the test questions?"**

Partly, and we design around it. The LLM only writes questions; it never grades them.

- Each answer must come with an exact quote, and we reject the question if that quote isn't in the source.
- A question the model can answer with no documents is dropped, so we test retrieval, not model memory.
- The known bias is that questions reuse the source's wording, which makes absolute scores optimistic. So we present *comparisons between configs*, where that bias applies equally to both sides.

**Q7. "How do you know the scores are right?"**

The grading is arithmetic, so it can be checked: a hit means a retrieved chunk from the right document contains the quote. Three checks back it up:

1. **Repeatable:** the same version run twice gives the same numbers.
2. **Sensitive:** a deliberately bad config (top-k 1, keyword-only) scores clearly lower.
3. **Agrees with people:** on a hand-checked sample, the automatic hit/miss matched a human on X of 20. *(Fill in before presenting.)*

**Q8. "Why only measure retrieval? What about hallucinations?"**

Retrieval comes first: if the right passage never reaches the prompt, no prompt or model can fix the answer. Barnett et al. place 3 of 7 failure points before generation. Retrieval scoring is also the part we can make repeatable without an LLM grader. Answer scoring is the next layer on top.

**Q9. "What happens when the documents change?"**

Test answers are anchored to a document and a quote, not to chunk IDs, so they survive re-chunking, a new parser or a new vector store. If an edit removes the quoted text, that question becomes stale; one click regenerates the set.

**Q10. "Why not just use RAGAS?"**

- **Grading:** RAGAS mostly uses an LLM to grade, so its scores vary between runs and every run costs money. Ours is repeatable and free to rerun.
- **Setup:** RAGAS is a library you wire into your own code. We're built into the place where the pipeline is made, versioned and compared.
- **Diagnosis:** we label every miss with its cause and a fix.

## Practical questions

**Q11. "How fast is it, and what does it cost?"**

| Step | Measured in our runs | Cost |
| --- | --- | --- |
| Generate a 30-question set | About 14 LLM calls (questions written 5 at a time, checked 10 at a time) | Within Gemini and NVIDIA free tiers |
| Score one question, no reranker | 17 ms median | None (all local) |
| Score one question, with reranker | 310–420 ms median | None (all local) |

Generating the set is a one-time cost. Re-scoring after a config change needs no LLM calls, which is what makes comparing many versions practical.

**Q12. "Does it scale?"**

Tested on a 517-chunk corpus of 10 documents. Everything runs in one process on SQLite and embedded vector stores, with no servers. That suits one team's knowledge base.

Known limits:

- Background jobs live in memory, so a restart cancels a running evaluation.
- Exact vector search slows down past roughly 50,000 chunks. The FAISS, LanceDB and Qdrant options are already in place for that point.

**Q13. "Is my data private? Can it run fully locally?"**

Parsing, embedding, reranking, search and scoring all run on the local machine. The LLM provider does receive document excerpts: when writing questions, and in normal chat. A local LLM would work in principle, since we use a standard OpenAI-compatible client, but it isn't built yet. Say that plainly.

## Product questions

**Q14. "Who pays for this, and why?"**

Two buyers, one engine:

- **Teams building RAG** use it to pick and defend a config, instead of guessing.
- **Documentation and support owners** are the bigger opportunity. A question that fails because the content is missing points to a gap in the docs. That becomes *"your docs can't answer 23% of what users ask; here are the missing topics"* (illustrative number). That ties the product to fewer support tickets, which a business already pays for.

Honest caveat: pure evaluation tools sell poorly because teams see them as "just a script". The documentation-health angle is how we avoid that.

**Q15. "What's built today versus planned?"**

| Status | Capability |
| --- | --- |
| Built | Full RAG builder: 8-stage configurable pipeline, 5 vector stores, versioning and rollback, chat playground with retrieval inspector |
| Built | Keyword, vector and exact-match search combined in one ranking |
| Built | Auto-generated test sets, repeatable retrieval scoring, diagnosis per miss, version comparison |
| Next | Automatic sweep over many configs, with caching so the corpus isn't re-embedded each time |
| Next | Leaderboard of quality against cost, and one-click "use this config" |
| Next | Report of documentation gaps and contradictions |
| Later | Real user questions fed back into the tests; agent-style retrieval measured as one more option; answer-quality scoring |

Never present a "Next" or "Later" row as built.

**Q16. "What would you build with more time?"**

The automatic sweep. The test set already exists, so trying 20 configs and showing the best trade-off between quality and cost is the natural next step. It turns *"measure your config"* into *"we find your config"*.

## Sources

- [Barnett et al., Seven Failure Points When Engineering a RAG System (arXiv 2401.05856)](https://arxiv.org/abs/2401.05856)
- [Chroma: Evaluating Chunking Strategies for Retrieval (2024)](https://www.trychroma.com/research/evaluating-chunking)
- [Zheng et al., Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena (arXiv 2306.05685)](https://arxiv.org/abs/2306.05685)
- [Thakur et al., BEIR benchmark (arXiv 2104.08663)](https://arxiv.org/abs/2104.08663)
- [AutoRAG (arXiv 2410.20878)](https://arxiv.org/abs/2410.20878)
- [KruxAI RAGBuilder (GitHub)](https://github.com/KruxAI/ragbuilder)
- [Ragas test set generation docs](https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/)
- Infosys Tech Compass, RAG Challenges & Solutions (practitioner report; full text in our research notes, IDEAS.md)
- [Example of the unsourced "80%" claim (dev.to) — do not cite](https://dev.to/ragprep/80-of-rag-failures-start-here-and-its-not-the-llm-11lp)
