# Contributing to RAGLabs

Thanks for helping. RAGLabs is Apache-2.0 licensed; contributions are accepted under the same license.

## Dev setup

```bash
cd backend && uv sync && uv run pytest -q    # ~240 tests, no API keys needed
cd frontend && npm install && npm run build  # type-check + production build
```

Run the app as described in the [README](README.md#from-source). Before opening a PR, both commands above must pass.
Read [`DEVELOPER_ARCHITECTURE.md`](DEVELOPER_ARCHITECTURE.md) for how the pieces fit.

## Where to contribute (the registries)

Most contributions are "register one class", no core changes:

| To add | Where | How |
|---|---|---|
| **Node type** (parser, chunker, embedder, retriever, reranker, prompt, generator, verifier) | `backend/app/nodes/<slot>.py` | Subclass the slot's base class and decorate with `@register("<slot>", "<type>", title=…, description=…)`. Give it a `Config` (`NodeConfig`) using `instant_field` / `rebuild_field`; the UI form is generated from it. Add a test. |
| **Vector store** | `backend/app/vectorstores/` | Implement the contract in `base.py` and register it; it must pass the shared store test suite (`tests/test_vectorstores.py`). |
| **LLM provider preset** | `backend/app/llm/presets.py` | Add a `Preset(...)` for any OpenAI-compatible endpoint. |
| **Docs page** | `frontend/src/features/docs/content/<slug>.md` | Write Markdown (first line `# Title`, then a one-sentence summary), then add the slug to `NAV` in `features/docs/pages.ts`. Supported: headings, tables, code fences, flat lists, `> **Note**`/`**Tip**`/`**Warning**` callouts, `/docs/<slug>` links |
| **Sweep axis / recipe** | `backend/app/engine/sweep.py`, `recipes.py` | Add an entry plus a test. |

## Pull requests

- Keep PRs focused; one feature or fix each. Describe the *why*.
- Add or update tests. Describe behaviour changes in the PR.
- API contract changes must be reflected in `frontend/API.md`.
- No new dependency for something a few lines of stdlib can do.
- Never commit API keys, `.env`, or the `data/` directory.

Look for issues labelled `good first issue`. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems: see [SECURITY.md](SECURITY.md), do not open a public issue.
