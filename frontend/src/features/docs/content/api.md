# API tab

The API tab turns your project into an HTTP service. Any script or app can send a question and get back the same cited answer you see in the Playground, from the project's **active version**. When you change the configuration or switch versions, callers get the new behaviour with no code change.

## Before you start

- The backend is running (by default at `http://127.0.0.1:8000`).
- The project has documents and an active version; the Playground already answers questions.
- An LLM is connected on the server. Callers do not need their own key.

## The query endpoint

```
POST /api/projects/{project_id}/chat
```

The tab shows your project's full URL, ready to copy. The body is JSON:

| Field | Required | Meaning |
| --- | --- | --- |
| `question` | Yes | The question, 1 to 8000 characters |
| `version_id` | No | Answer with a specific version instead of the active one |
| `stream` | No | `false` returns one JSON response; `true` (the default) streams Server-Sent Events |

## Try it

The **Try it** card sends a real, non-streaming request and shows the raw JSON. Type a question about your documents, click **Send request**, and you see exactly what your code will receive. If it fails, a banner shows the error.

## Call it from code

The **Request** card has snippets for curl, Python and JavaScript with your URL filled in, plus a streaming example.

```bash
curl -X POST http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the dataset about?", "stream": false}'
```

```python
import requests

res = requests.post(
    "http://127.0.0.1:8000/api/projects/YOUR_PROJECT_ID/chat",
    json={"question": "What is the dataset about?", "stream": False},
    timeout=120,
)
res.raise_for_status()
data = res.json()
print(data["answer"])
for c in data["citations"]:
    print(f"[{c['n']}] {c['document']} - {c['heading_path']}")
```

> **Note** In Windows PowerShell the curl snippet's quoting does not work. Use `Invoke-RestMethod` with a body built by `ConvertTo-Json`.

## The response

With `stream: false` the response contains:

| Field | What it holds |
| --- | --- |
| `answer` | The answer text, with citation markers like `[1]` |
| `citations` | One entry per marker: `n`, `document`, `page_start` and `page_end`, `heading_path`, and `spans` (character ranges in the cited chunk that support the claim) |
| `sources` | Every retrieved chunk in rank order: `rank`, `document`, pages, `heading_path`, `found_by`, `scores`, `cited` and `text` |
| `run_id` | The ID of this run; it appears in the Playground's recent runs |
| `totals` | `latency_ms`, `tokens_in`, `tokens_out`, `cost_usd` |

To show sources to your users, loop over `citations` and match each `n` to the `[n]` markers in `answer`. The **Response** card shows a real response from your latest successful run.

## Streaming

With `"stream": true` the response is a stream of events:

`status` (only if the index is being rebuilt), then `run`, `retrieval`, many `token` events, and finally `done` or `error`. Each event's `data:` line is JSON with a `type` field. The endpoint is a `POST`, so a browser's `EventSource` cannot read it; use an HTTP client that supports streaming.

```python
import json
import requests

with requests.post(URL, json={"question": "...", "stream": True}, stream=True, timeout=300) as res:
    res.raise_for_status()
    for line in res.iter_lines(decode_unicode=True):
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:])
        if event["type"] == "token":
            print(event["text"], end="", flush=True)
        elif event["type"] == "error":
            raise RuntimeError(event["message"])
```

## Pin a version

By default every call uses the active version. To keep a caller on one version while you experiment, add its ID as `version_id`. List versions with `GET /api/projects/{project_id}/versions`.

## Errors

Errors return JSON with a `detail` field.

| Status | Meaning | Fix |
| --- | --- | --- |
| `401` | A remote call without a valid key | Send `Authorization: Bearer rl_...` |
| `404` | Project or `version_id` not found | Check the IDs |
| `409` | The project has no documents, or its index build failed | Add documents or fix the build |
| `422` | Invalid body, for example an empty `question` | Send 1 to 8000 characters |
| `502` | The LLM provider failed (no key, rate limit, overload) | Check the provider and retry |

In streaming mode, errors arrive as an `error` event.

## API keys

Requests from the machine running RAGLabs (the web UI included) need no key. Any other caller must send `Authorization: Bearer rl_...`.

1. In **API keys**, choose a name and a scope: **Chat** (this project's query endpoint only) or **Admin** (the whole API).
2. Click **Create key** and copy it immediately; it is shown once. Only a hash is stored.
3. Revoke a key at any time.

> **Warning** Behind a reverse proxy every request appears to come from the local machine. Set `TRUST_LOOPBACK=false` in the server's environment so that every call needs a key.

## Usage

The usage dashboard shows requests per day, errors, end-to-end p50 latency, tokens and cost, for the last 30 or 90 days, broken down by source (Playground or API) and by key.

## Limits and notes

- **Local by default.** The server answers only to localhost host names (`ALLOWED_HOSTS`). To serve other machines, add their host names, run behind a proxy you trust, and use keys.
- **No browser calls from other sites.** The backend sends no CORS headers, so JavaScript on another origin is blocked. Call the API from a server, script or Node app.
- **The first call after a rebuild-type change is slow**, because the index is rebuilt first (a `status` event when streaming).
- Every API call is recorded as a run, visible in the Playground's recent runs with its sources and trace.

## API tab or Export RAG?

Use the API tab when apps should call your pipeline over HTTP and pick up changes live. Use **Export RAG** (on the Versions tab) to ship a frozen pipeline inside another project. See [Versions](/docs/versions).

For every endpoint, including evaluation, see the interactive OpenAPI reference linked at the bottom of the docs sidebar.
