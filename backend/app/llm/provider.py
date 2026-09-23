"""OpenAI-compatible provider adapter.

Gemini and NVIDIA both expose OpenAI-compatible endpoints, so one client type
covers both; a provider is just a base URL, a key, and some defaults. The
OpenAI SDK retries 429/5xx with backoff (honouring retry-after) on its own.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from ..config import get_settings


@dataclass(frozen=True)
class Provider:
    name: str
    title: str
    signup_url: str

    @property
    def base_url(self) -> str:
        return getattr(get_settings(), f"{self.name}_base_url")

    @property
    def api_key(self) -> str:
        return getattr(get_settings(), f"{self.name}_api_key")

    @property
    def default_model(self) -> str:
        return getattr(get_settings(), f"{self.name}_default_model")

    @property
    def default_embed_model(self) -> str:
        return getattr(get_settings(), f"{self.name}_default_embed_model")


# Tried in order when the configured default model is no longer offered — free-tier
# catalogs change often, and a retired model returns HTTP 410.
PREFERRED: dict[tuple[str, str], tuple[str, ...]] = {
    ("gemini", "chat"): ("gemini-2.5-flash", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash-lite"),
    ("gemini", "embed"): ("gemini-embedding-001", "gemini-embedding-2"),
    # Verified callable and fast (2026-09-23). NVIDIA's /models lists entries that
    # 404 or hang, so being listed isn't enough — keep this list tested.
    ("nvidia", "chat"): ("nvidia/nemotron-3-super-120b-a12b", "deepseek-ai/deepseek-v4.1-flash"),
    ("nvidia", "embed"): ("nvidia/llama-3.2-nv-embedqa-1b-v1", "nvidia/nv-embedqa-mistral-7b-v2", "nvidia/embed-qa-4"),
}

PROVIDERS: dict[str, Provider] = {
    "gemini": Provider("gemini", "Google Gemini", "https://aistudio.google.com/apikey"),
    "nvidia": Provider("nvidia", "NVIDIA", "https://build.nvidia.com"),
}


class ProviderError(Exception):
    """An error with a message fit to show the user."""


def availability(name: str) -> tuple[bool, str]:
    p = PROVIDERS[name]
    if not p.api_key:
        return False, f"Add {name.upper()}_API_KEY to .env (free key: {p.signup_url})"
    return True, ""


_clients: dict[str, AsyncOpenAI] = {}


def client(name: str) -> AsyncOpenAI:
    ok, reason = availability(name)
    if not ok:
        raise ProviderError(reason)
    if name not in _clients:
        p = PROVIDERS[name]
        # Fail a hung model in about a minute rather than retrying for many.
        _clients[name] = AsyncOpenAI(api_key=p.api_key, base_url=p.base_url, max_retries=2,
                                     timeout=httpx.Timeout(60.0, connect=10.0))
    return _clients[name]


def friendly_error(provider: str, e: Exception) -> ProviderError:
    title = PROVIDERS[provider].title if provider in PROVIDERS else provider
    if isinstance(e, ProviderError):
        return e
    if isinstance(e, openai.RateLimitError):
        return ProviderError(
            f"{title} rate limit or free quota reached. Wait a minute and retry, or switch provider."
        )
    if isinstance(e, openai.AuthenticationError):
        return ProviderError(f"{title} rejected the API key. Check it in .env.")
    if isinstance(e, openai.APITimeoutError):
        return ProviderError(f"{title} didn't respond in time. The model may be overloaded — retry, or pick another.")
    if isinstance(e, openai.APIStatusError) and e.status_code == 410:
        return ProviderError(f"{title} has retired this model. Pick another model in Configure → Generate.")
    if isinstance(e, openai.NotFoundError):
        return ProviderError(f"{title} doesn't recognise that model. Pick another in Configure.")
    if isinstance(e, openai.BadRequestError):
        return ProviderError(f"{title} rejected the request: {getattr(e, 'message', e)}")
    if isinstance(e, openai.APIConnectionError):
        return ProviderError(f"Can't reach {title}. Check your internet connection.")
    if isinstance(e, openai.APIStatusError):
        return ProviderError(f"{title} error {e.status_code}: {getattr(e, 'message', e)}")
    msg = str(e).strip() or type(e).__name__
    if "overload" in msg.lower() or "unavailable" in msg.lower():
        return ProviderError(f"{title} is temporarily overloaded. Retry in a moment, or switch provider.")
    return ProviderError(f"{title} call failed: {msg}")


# --- model listing ----------------------------------------------------------

_EXCLUDE_CHAT = ("embed", "rerank", "imagen", "veo", "tts", "aqa", "clip", "whisper",
                 "parse", "guard", "safety", "detector", "-image", "audio", "vision-only")

_model_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}
_MODEL_TTL = 600


async def list_models(name: str, kind: str = "chat") -> list[str]:
    """Models the provider offers, filtered to chat or embedding models.
    Falls back to the configured default if listing fails."""
    p = PROVIDERS[name]
    fallback = [p.default_model if kind == "chat" else p.default_embed_model]
    if not availability(name)[0]:
        return fallback
    key = (name, kind)
    hit = _model_cache.get(key)
    if hit and time.monotonic() - hit[0] < _MODEL_TTL:
        return hit[1]
    try:
        page = await client(name).models.list()
        ids = [m.id.removeprefix("models/") for m in page.data]
    except Exception:
        return fallback
    if kind == "chat":
        ids = [i for i in ids if not any(x in i.lower() for x in _EXCLUDE_CHAT)]
    else:
        ids = [i for i in ids if "embed" in i.lower()]
    ids = sorted(set(ids)) or fallback
    default = _pick_default(name, kind, ids)
    if default in ids:
        ids.remove(default)
        ids.insert(0, default)
    _model_cache[key] = (time.monotonic(), ids)
    return ids


def _pick_default(name: str, kind: str, ids: list[str]) -> str:
    p = PROVIDERS[name]
    configured = p.default_model if kind == "chat" else p.default_embed_model
    for m in (configured, *PREFERRED.get((name, kind), ())):
        if m in ids:
            return m
    return ids[0] if ids else configured


async def resolve_model(name: str, kind: str = "chat") -> str:
    """The model to use when none is chosen: the configured default if the
    provider still offers it, else the first preferred model it does offer."""
    models = await list_models(name, kind)
    return models[0]


# Free tiers cost nothing. Tokens are still recorded so costs can be priced later.
def cost_usd(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    return 0.0


def usage_tokens(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)


def reasoning_tokens(usage: Any) -> int | None:
    """Hidden 'thinking' tokens, when the provider reports them. They count
    against max_tokens, which is why thinking models can truncate answers."""
    details = getattr(usage, "completion_tokens_details", None) if usage is not None else None
    n = getattr(details, "reasoning_tokens", None) if details is not None else None
    return int(n) if n is not None else None
