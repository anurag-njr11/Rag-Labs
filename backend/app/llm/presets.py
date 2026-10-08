"""Built-in provider presets.

A preset is just a known OpenAI-compatible endpoint plus sensible defaults, so
connecting one as the Generate LLM only takes an API key. Anything not listed here can still be
added as a custom provider (any base URL that speaks the OpenAI API: vLLM,
LiteLLM proxy, Azure AI Foundry, a corporate gateway, …).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    title: str
    base_url: str
    signup_url: str = ""
    description: str = ""
    default_model: str = ""
    # Only Gemini and NVIDIA back the Embed slot's "api" type (app/nodes/embed.py).
    default_embed_model: str = ""
    # Local servers (Ollama, LM Studio) take no key; they're enabled by adding them.
    key_required: bool = True
    # Whether the endpoint accepts `reasoning_effort` (incl. "none"). Providers that
    # don't get "default" (send nothing) as their reasoning default.
    supports_reasoning: bool = False
    # Always registered as a Generate type, configured or not, so the default pipeline
    # ("gemini" when nothing is connected) stays valid. The UI only lists connected ones.
    pinned: bool = False


PRESETS: dict[str, Preset] = {p.name: p for p in (
    Preset("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
           "https://aistudio.google.com/apikey", "Free tier via Google AI Studio.",
           "gemini-3.5-flash", "gemini-embedding-001",
           supports_reasoning=True, pinned=True),
    Preset("nvidia", "NVIDIA", "https://integrate.api.nvidia.com/v1",
           "https://build.nvidia.com", "Free tier via build.nvidia.com — Llama, Mistral, Nemotron and more.",
           "nvidia/nemotron-3-super-120b-a12b", "nvidia/llama-3.2-nv-embedqa-1b-v1",
           supports_reasoning=True, pinned=True),
    Preset("openai", "OpenAI", "https://api.openai.com/v1",
           "https://platform.openai.com/api-keys", "GPT models.",
           "gpt-5-mini"),
    Preset("anthropic", "Anthropic", "https://api.anthropic.com/v1/",
           "https://console.anthropic.com/settings/keys", "Claude models via the OpenAI-compatible endpoint.",
           "claude-sonnet-5-5"),
    Preset("groq", "Groq", "https://api.groq.com/openai/v1",
           "https://console.groq.com/keys", "Very fast inference for open models.",
           "llama-3.3-70b-versatile"),
    Preset("mistral", "Mistral AI", "https://api.mistral.ai/v1",
           "https://console.mistral.ai/api-keys", "Mistral and Magistral chat models.",
           "mistral-small-latest"),
    Preset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
           "https://openrouter.ai/keys", "One key for hundreds of models from many vendors.",
           "openrouter/auto"),
    Preset("together", "Together AI", "https://api.together.xyz/v1",
           "https://api.together.ai/settings/api-keys", "Hosted open-weight models.",
           "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    Preset("deepseek", "DeepSeek", "https://api.deepseek.com/v1",
           "https://platform.deepseek.com/api_keys", "DeepSeek chat and reasoning models.",
           "deepseek-chat"),
    Preset("ollama", "Ollama (local)", "http://localhost:11434/v1",
           "https://ollama.com/download", "Models running on your machine via Ollama. No key needed.",
           "llama3.2", key_required=False),
    Preset("lmstudio", "LM Studio (local)", "http://localhost:1234/v1",
           "https://lmstudio.ai", "Models served by LM Studio's local server. No key needed.",
           key_required=False),
)}
