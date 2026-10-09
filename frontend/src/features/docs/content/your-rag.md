# Evaluate your own RAG

Already have a RAG built with LangChain, LlamaIndex or your own code? You do not have to rebuild it in RAGLabs to measure it. Connect it over HTTP and score it on the same questions as your RAGLabs pipelines.

## What you get

The same retrieval metrics (Hit@k, MRR, nDCG), latency and optional answer grading as a pipeline, and a row in **Run history** next to your RAGLabs versions. That makes the comparison direct: your system's MRR next to the best configuration a sweep found.

## What you need

1. A RAGLabs project with the **same documents** your system searches. The quickest way is **New project**, then **Evaluate a RAG I already have**: it asks for a name and your documents, then takes you to Evaluate.
2. An **eval set** for those documents: generate one (this builds the project's default index first), or import your own with CSV. See [Evaluate](/docs/evaluate).
3. An **HTTP endpoint** on your system that accepts a question and returns the answer and the passages it retrieved.

## The endpoint contract

RAGLabs sends:

```json
POST https://your-host/ask
{"question": "How many times are failed uploads retried?"}
```

and expects a JSON response like:

```json
{
  "answer": "Three times, with exponential backoff.",
  "contexts": [
    {"text": "The upload worker retries failed uploads three times ...", "source": "uploads.md", "score": 0.83}
  ]
}
```

- `contexts` is the list of passages your system retrieved, in rank order. Only the text is required.
- `source` is the file name, path or URL of the document the passage came from. It is optional (see scoring below).
- `answer` is optional. Without it, the system is scored on retrieval only.

## Connect it

1. Open **Evaluate**, then **Your RAG**.
2. Enter a name and the endpoint URL. Put credentials in the **auth header** (for example `Authorization` with `Bearer ...`), never in the URL; URLs that contain credentials are rejected. The header value is stored encrypted and is never shown again.
3. If your API returns a different shape, open **Response mapping** and adjust the paths.
4. Click **Test with one question**. You see the question, the latency, the answer, and the first passages with their sources, so you can fix the mapping before running anything. Nothing is saved by testing.
5. Click **Save**.

### Response mapping

Paths are dotted, with numbers for list positions, for example `data.hits.0.doc.body`.

| Field | Default | Meaning |
| --- | --- | --- |
| Question field | `question` | The JSON key the question is sent in |
| Answer path | `answer` | Where the answer is; empty means retrieval only |
| Contexts path | `contexts` | The list of retrieved passages |
| Text path | `text` | The passage text inside one context; empty means the context itself is the text |
| Source path | `source` | The passage's document; empty means judge on text alone |
| Passages scored per question | 8 | Hit@k and MRR look at this many (1 to 50) |

## Run the evaluation

In **Retrieval quality**, choose *Your RAG: name* in the version menu and click **Run evaluation**. The scorecard and per-question table work as for any run, and the run appears in Run history under your system's name.

To grade answers, turn on **Also grade answers** and pick a **Judge model** first: your system has no RAGLabs model of its own to do the grading.

## How scoring works

A returned passage is a **hit** for a question when:

1. it contains the question's evidence (verbatim, or with nearly all of its words), and
2. if it names a `source`, that source is the question's document file (the file name is compared; folders and URL query strings are ignored). If it names no source, the evidence match alone decides.

Only what can be observed from outside is diagnosed. A miss is **Not retrieved** (the evidence was not in the passages returned), and, when you grade answers, the answer-level causes apply. Causes that need RAGLabs's internals, such as the reranker and context budget, do not apply, and there is no one-click fix.

Cost per 1,000 queries is not reported, because RAGLabs cannot see what your system spends. Latency is the round-trip time of each request, measured one question at a time.

If a request fails (timeout, HTTP error, or a response that does not match the mapping), that question counts as a miss and the run reports how many errored. If every request fails, the run fails with the first error.

## Your RAG is a Python function

You do not need an API. Install the `raglabs` package next to your code and either serve the function on the contract above, or score it in-process:

```python
import raglabs

@raglabs.system
def ask(question):
    hits = retriever.invoke(question)
    return {"answer": chain.invoke(question),
            "contexts": [{"text": h.page_content, "source": h.metadata["source"]} for h in hits]}

raglabs.serve(ask, port=8100)              # then connect http://127.0.0.1:8100 here
print(raglabs.evaluate(ask, "eval.csv"))   # or: scores in-process, no server
```

The function may be sync or async. It can return the contract dict, a list of passages (retrieval only), or an `(answer, passages)` tuple, and a passage may be a plain string. In a notebook or other async code, use `await raglabs.aevaluate(...)`. For CI, see [CLI and CI](/docs/cli).

## Per-step latency and tokens (OpenTelemetry)

Each question is sent with a W3C `traceparent` header. If your system is instrumented with OpenTelemetry and keeps that trace context, point its exporter at RAGLabs:

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:8000/api/otel/v1/traces
```

Its spans then show up on the run: **Inside your system** lists each step's p50 and p95 latency and mean tokens across questions, and each question's details show its trace as a timeline. Tokens are read from the `gen_ai.usage.input_tokens` / `output_tokens` attributes (the OpenTelemetry GenAI conventions, and the older `prompt_tokens` / `completion_tokens` names), and the model from `gen_ai.request.model`; a model RAGLabs knows the price of also gets a cost.

> **Note** Exporters batch spans, so the last questions' traces can arrive a few seconds after the run ends. They are matched when the run is shown, so reopen it to see them. Spans are kept for 30 days.

Protobuf (the default for OTLP over HTTP) and JSON are both accepted, gzipped or not. From another machine, the exporter needs a RAGLabs API key of any scope: `OTEL_EXPORTER_OTLP_TRACES_HEADERS=Authorization=Bearer%20rl_...`.

## Tips

- Match the **documents**. If your system indexes different files than the project, evidence will not be found and scores will be misleadingly low.
- Make `source` match the file names you uploaded. A source that names a title instead of a file will turn real hits into misses; clear **Source path** to judge on text alone.
- Use the same eval set for every comparison, and the same number of passages (`top_k`) when comparing with a RAGLabs configuration.
- To gate a deployment on these numbers, use the command line: see [CLI and CI](/docs/cli).
