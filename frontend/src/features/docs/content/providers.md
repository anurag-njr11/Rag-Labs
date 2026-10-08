# LLM providers

The **LLM providers** page (top bar) connects the language models used to write answers, generate eval questions, grade answers and run the optional Verify and agentic steps.

## Connect a provider

Built-in providers are known OpenAI-compatible endpoints; connecting one only needs an API key.

| Provider | Notes |
| --- | --- |
| Google Gemini | Free tier through Google AI Studio |
| NVIDIA | Free tier through build.nvidia.com |
| OpenAI, Anthropic, Groq, Mistral AI, OpenRouter, Together AI, DeepSeek | Bring your own key |
| Ollama and LM Studio (local) | No key; enabled by adding them |

Under **More providers**, pick one and enter its key. Use **Test** to check the connection before relying on it. Connected providers appear as choices in the Generate stage, and any model of a connected provider can act as the judge in [Evaluate](/docs/evaluate).

Providers can also be enabled from the server's environment: copy `.env.example` to `.env` and set `GEMINI_API_KEY`, `NVIDIA_API_KEY` or `<NAME>_API_KEY` for any preset (for example `OPENAI_API_KEY`), or `OLLAMA_BASE_URL` for a local server. Every preset also reads `<NAME>_BASE_URL` and `<NAME>_DEFAULT_MODEL`.

## Custom endpoints

Choose **Custom endpoint** for anything that speaks the OpenAI API: vLLM, a LiteLLM proxy, Azure AI Foundry, or a company gateway.

| Field | Meaning |
| --- | --- |
| Display name | How it appears in the Generate stage |
| Base URL | The endpoint's `/v1` root |
| API key | Stored encrypted; leave empty if not required |
| Default model | Used when a stage leaves the model empty |
| Requires an API key | Whether the endpoint refuses calls without one |
| Supports reasoning effort | Whether it accepts a reasoning-effort setting |
| Extra HTTP headers | Sent with every request (stored encrypted) |

## Embedding models

The Embed stage's local models need no provider. Its **API model** option uses Gemini or NVIDIA embeddings and so needs one of those two keys.

## How keys are protected

- Keys entered in the app are encrypted (AES-256-GCM) with a master key created on first run in your user configuration folder, not in `data/`. **Back it up**: without it, stored keys must be re-entered. You can supply your own with `RAGLABS_SECRET_KEY` or `RAGLABS_SECRET_KEY_FILE`.
- A stored key is only ever sent to the base URL it was saved with. Changing the URL means entering the key again.
- Secrets are scrubbed from logs and error messages.
- The backend answers only to localhost host names, which blocks DNS-rebinding attacks from web pages.

## Labs

The **Labs** switch on this page reveals research-grade tools: attested computations (the Computations tab and the Compute stage), the embedding adapter and prompt optimisation. See [Computations](/docs/data) and [Advanced evaluation](/docs/advanced-evaluation). The setting is stored in your browser.

## Costs

Prices shown in RAGLabs are paid-tier list prices per million tokens. Free tiers cost nothing, but the figures let you compare configurations as if you were paying. A model with no published price shows a dash, never zero.
