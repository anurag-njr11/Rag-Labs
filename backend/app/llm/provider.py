"""LLM provider registry and OpenAI-compatible client adapter.

Every supported provider exposes an OpenAI-compatible endpoint, so one client
type covers all of them; a provider is just a base URL, a key, and some
defaults. The OpenAI SDK retries 429/5xx with backoff (honouring retry-after)
on its own.

Providers come from three places, later ones overriding earlier ones field by
field:

  1. Built-in presets (`presets.py`) — Gemini, NVIDIA, OpenAI, Anthropic, …
  2. Environment / .env — `<NAME>_API_KEY`, `<NAME>_BASE_URL`,
     `<NAME>_DEFAULT_MODEL`, `<NAME>_DEFAULT_EMBED_MODEL` for any preset, plus
     `LLM_PROVIDERS` (a JSON list) for custom endpoints defined as code.
  3. The database — providers added or edited in the UI (Settings → Providers).

These providers back the Generate slot. The Embed slot's "api" type still only
uses Gemini and NVIDIA (their `default_embed_model` comes from the presets/env).

`PROVIDERS` holds the providers that are offered: the pinned presets (Gemini,
NVIDIA) plus every provider that has been configured somewhere. It is mutated
in place by `refresh()`, so module-level references to it stay valid.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx
import openai
from dotenv import dotenv_values
from openai import AsyncOpenAI

from .. import db, vault
from ..config import BACKEND_DIR, REPO_DIR
from .presets import PRESETS, Preset

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
RESERVED = {"presets", "test"}  # collide with /api/providers/presets and /api/providers/test


@dataclass(frozen=True)
class Provider:
    name: str
    title: str
    base_url: str
    # repr=False: a logged or traceback-printed Provider never shows its secrets.
    api_key: str = field(default="", repr=False)
    default_model: str = ""
    default_embed_model: str = ""
    signup_url: str = ""
    description: str = ""
    key_required: bool = True
    supports_reasoning: bool = False
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    # "preset" (untouched built-in), "env", "ui", or "custom-env" / "custom-ui".
    source: str = "preset"
    preset: str | None = None
    # Set when a stored secret couldn't be decrypted (e.g. the secret key changed).
    secret_error: str = ""

    @property
    def key_env(self) -> str:
        return env_prefix(self.name) + "_API_KEY"

    @property
    def custom(self) -> bool:
        return self.preset is None

    def public(self) -> dict[str, Any]:
        """Safe to send to the browser: the key is reduced to a hint."""
        d = asdict(self)
        d.pop("api_key")
        d["headers"] = sorted(self.headers)
        d["base_url"] = vault.redact_url(self.base_url)
        d["key_set"] = bool(self.api_key)
        d["key_hint"] = ("…" + self.api_key[-4:]) if len(self.api_key) >= 8 else ("set" if self.api_key else "")
        d["key_env"] = self.key_env
        d["custom"] = self.custom
        return d


def env_prefix(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


# --- configuration sources --------------------------------------------------

_dotenv: dict[str, str] | None = None


def _env(key: str) -> str:
    """os.environ first, then the repo's / backend's .env (like Settings)."""
    global _dotenv
    if key in os.environ:
        return os.environ[key]
    if _dotenv is None:
        _dotenv = {}
        for path in (REPO_DIR / ".env", BACKEND_DIR / ".env"):
            if path.exists():
                _dotenv.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    return _dotenv.get(key, "")


def _from_preset(p: Preset) -> Provider:
    return Provider(name=p.name, title=p.title, base_url=p.base_url, default_model=p.default_model,
                    default_embed_model=p.default_embed_model, signup_url=p.signup_url,
                    description=p.description, key_required=p.key_required,
                    supports_reasoning=p.supports_reasoning, preset=p.name)


_OVERRIDABLE = ("title", "base_url", "api_key", "default_model", "default_embed_model",
                "supports_reasoning", "key_required", "headers")


def _merge(base: Provider, over: dict[str, Any], source: str) -> Provider:
    """Overlay the non-empty fields of `over` onto `base`."""
    kw = {k: over[k] for k in _OVERRIDABLE if over.get(k) not in (None, "", {})}
    if over.get("api_key_env"):
        kw["api_key"] = _env(over["api_key_env"]) or kw.get("api_key", "")
    if over.get("_secret_error"):
        kw["secret_error"] = over["_secret_error"]
    return Provider(**{**asdict(base), **kw, "source": source})


def _env_overrides(name: str) -> dict[str, str]:
    pre = env_prefix(name)
    return {k: _env(f"{pre}_{k.upper()}") for k in ("api_key", "base_url", "default_model", "default_embed_model")}


def _custom_from_env() -> list[dict[str, Any]]:
    raw = _env("LLM_PROVIDERS").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            raise TypeError("expected a JSON list")
    except (TypeError, ValueError) as e:
        log.warning("Ignoring LLM_PROVIDERS: %s", e)
        return []
    out = []
    for it in items:
        if not isinstance(it, dict) or not NAME_RE.match(str(it.get("name", ""))) or not it.get("base_url"):
            log.warning("Ignoring LLM_PROVIDERS entry (needs a lowercase name and a base_url): %r", it)
            continue
        out.append(it)
    return out


def _blank(name: str, row: dict[str, Any]) -> Provider:
    return Provider(name=name, title=row.get("title") or name, base_url=row.get("base_url", ""),
                    key_required=bool(row.get("key_required", False)), description="Custom OpenAI-compatible endpoint.")


# --- registry ---------------------------------------------------------------

PROVIDERS: dict[str, Provider] = {}
_db_rows: dict[str, dict[str, Any]] = {}
_listeners: list[Callable[[], None]] = []


def on_change(fn: Callable[[], None]) -> None:
    """Call `fn` after every refresh (e.g. to sync Generate node types)."""
    _listeners.append(fn)


def _configured(p: Provider) -> bool:
    return p.source != "preset" and (bool(p.api_key) or not p.key_required)


def resolve_all() -> dict[str, Provider]:
    """Every known provider (offered or not), after applying all sources."""
    out: dict[str, Provider] = {}
    for name, preset in PRESETS.items():
        p = _from_preset(preset)
        env = _env_overrides(name)
        if any(env.values()):
            p = _merge(p, env, "env")
        out[name] = p
    for row in _custom_from_env():
        name = row["name"]
        base = out.get(name) or _blank(name, row)
        out[name] = _merge(base, row, "env" if name in PRESETS else "custom-env")
    for name, row in _db_rows.items():
        base = out.get(name) or _blank(name, row)
        out[name] = _merge(base, row, "ui" if name in PRESETS else "custom-ui")
    return out


def refresh() -> None:
    global _dotenv
    _dotenv = None
    every = resolve_all()
    _secrets[:] = [s for p in every.values() for s in (p.api_key, *p.headers.values()) if s]
    offered = {n: p for n, p in every.items()
               if (n in PRESETS and PRESETS[n].pinned) or _configured(p)}
    PROVIDERS.clear()
    PROVIDERS.update(offered)
    _clients.clear()
    _model_cache.clear()
    for fn in _listeners:
        fn()


def _ctx(name: str, column: str) -> str:
    return f"llm_providers:{name}:{column}"


def _decrypt_row(r: dict[str, Any]) -> bool:
    """Decrypt a DB row in place. Returns True if it held plaintext secrets
    (written before encryption existed) and should be re-saved encrypted."""
    name, legacy = r["name"], False
    raw_key, raw_headers = r.get("api_key") or "", r.get("headers") or ""
    try:
        if vault.is_encrypted(raw_key):
            r["api_key"] = vault.decrypt(raw_key, _ctx(name, "api_key"))
        elif raw_key:
            legacy = True
        if vault.is_encrypted(raw_headers):
            r["headers"] = db.loads(vault.decrypt(raw_headers, _ctx(name, "headers")), {})
        else:
            r["headers"] = db.loads(raw_headers, {})
            legacy = legacy or bool(r["headers"])
    except vault.VaultError as e:
        log.error("Stored secrets for provider %r can't be decrypted: %s", name, e)
        r["api_key"], r["headers"] = "", {}
        r["_secret_error"] = ("Its stored API key can't be decrypted (the secret key changed?). "
                              "Re-enter the key in Settings → Providers.")
        r["_raw"] = (raw_key, raw_headers)  # kept untouched in the DB until the user re-enters
    return legacy


async def load() -> None:
    """Read UI-managed providers from the database (decrypting their secrets),
    and encrypt any secrets still stored in plain text. Call once after connecting."""
    rows = await db.fetch_all("SELECT * FROM llm_providers")
    _db_rows.clear()
    legacy = []
    for r in rows:
        if _decrypt_row(r):
            legacy.append(r["name"])
        for b in ("supports_reasoning", "key_required"):
            if r.get(b) is not None:
                r[b] = bool(r[b])
        _db_rows[r["name"]] = r
    for name in legacy:
        await _write(name, _db_rows[name])
    if legacy:
        # secure_delete zeroed the old pages; flush the WAL so no plaintext copy lingers there either.
        await db.conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        log.info("Encrypted stored API keys for %d provider(s).", len(legacy))
    refresh()


async def _write(name: str, row: dict[str, Any]) -> None:
    now = db.now_iso()
    if row.get("_raw"):  # undecryptable secrets: leave the stored ciphertext as it was
        enc_key, enc_headers = row["_raw"]
    else:
        enc_key = vault.encrypt(row.get("api_key") or "", _ctx(name, "api_key"))
        headers = row.get("headers") or {}
        enc_headers = vault.encrypt(db.dumps(headers), _ctx(name, "headers")) if headers else "{}"
    async with db.tx() as c:
        await c.execute(
            """INSERT INTO llm_providers (name, title, base_url, api_key, default_model,
                   supports_reasoning, key_required, headers, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET title=excluded.title, base_url=excluded.base_url,
                   api_key=excluded.api_key, default_model=excluded.default_model,
                   supports_reasoning=excluded.supports_reasoning, key_required=excluded.key_required,
                   headers=excluded.headers, updated_at=excluded.updated_at""",
            (name, row.get("title") or "", row.get("base_url") or "", enc_key,
             row.get("default_model") or "", _opt_bool(row.get("supports_reasoning")),
             _opt_bool(row.get("key_required")), enc_headers, row.get("created_at") or now, now),
        )
    row.setdefault("created_at", now)


async def save(name: str, fields: dict[str, Any]) -> Provider:
    """Create or update a UI-managed provider (or a preset's UI overrides).
    Fields left out keep their stored value; an empty api_key keeps the stored key.
    Secrets are encrypted before they reach the database."""
    if name in RESERVED:
        raise ProviderError(f"{name!r} is reserved; pick another name.")
    if not NAME_RE.match(name):
        raise ProviderError("Name must be 2–32 chars: lowercase letters, digits, '-' or '_', starting with a letter.")
    fields = {k: v for k, v in fields.items() if v is not None}
    if fields.get("api_key") == "":
        fields.pop("api_key")
    base_url = fields.get("base_url")
    if base_url and vault.url_has_credentials(base_url):
        raise ProviderError("Put credentials in the API key or headers fields, not in the base URL — "
                            "URLs are stored and shown unencrypted.")
    current = resolve_all().get(name)
    if (base_url and current and base_url.rstrip("/") != current.base_url.rstrip("/")
            and ((current.api_key and "api_key" not in fields) or (current.headers and "headers" not in fields))):
        # Otherwise a stored key could be redirected to a server it was never meant for.
        raise ProviderError("Re-enter the API key (and any headers) when changing the base URL, "
                            "so a stored key is never sent to a different server.")
    row = {**_db_rows.get(name, {}), **fields}
    if "api_key" in fields or "headers" in fields:  # re-entered: replaces undecryptable secrets
        row.pop("_raw", None)
        row.pop("_secret_error", None)
    if name not in PRESETS and not (row.get("base_url") or (current.base_url if current else "")):
        raise ProviderError("A custom provider needs a base URL.")
    await _write(name, row)
    _db_rows[name] = row
    refresh()
    return resolve_all()[name]


_secrets: list[str] = []


def known_secrets() -> list[str]:
    """Every secret value currently configured (refreshed by `refresh()`), for redaction.
    Cached rather than computed per call: the log filter calls this for every record."""
    return _secrets


vault.register_known_secrets(known_secrets)


async def remove(name: str) -> None:
    """Forget a UI-managed provider. A preset falls back to its env/default settings."""
    async with db.tx() as c:
        await c.execute("DELETE FROM llm_providers WHERE name=?", (name,))
    _db_rows.pop(name, None)
    refresh()


def _opt_bool(v: Any) -> int | None:
    return None if v is None else int(bool(v))


class ProviderError(Exception):
    """An error with a message fit to show the user."""


def get(name: str) -> Provider:
    p = PROVIDERS.get(name) or resolve_all().get(name)
    if p is None:
        raise ProviderError(f"Unknown LLM provider {name!r}. Add it in Settings → Providers.")
    return p


def availability(name: str) -> tuple[bool, str]:
    p = PROVIDERS.get(name) or resolve_all().get(name)
    if p is None:
        return False, f"Unknown provider {name!r} — add it in Settings → Providers."
    if not p.base_url:
        return False, f"{p.title} has no base URL. Set it in Settings → Providers."
    if p.secret_error:
        return False, p.secret_error
    if p.key_required and not p.api_key:
        hint = f" (key: {p.signup_url})" if p.signup_url else ""
        return False, f"Add an API key in Settings → Providers, or set {p.key_env} in .env{hint}"
    if name not in PROVIDERS:
        return False, f"{p.title} isn't enabled. Add it in Settings → Providers."
    return True, ""


_clients: dict[str, AsyncOpenAI] = {}


def _make_client(base_url: str, api_key: str, headers: dict[str, str] | None = None) -> AsyncOpenAI:
    # Local servers ignore the key, but the SDK insists on one.
    # Fail a hung model in about a minute rather than retrying for many.
    return AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url, max_retries=2,
                       default_headers=headers or None, timeout=httpx.Timeout(60.0, connect=10.0))


def client(name: str) -> AsyncOpenAI:
    ok, reason = availability(name)
    if not ok:
        raise ProviderError(reason)
    if name not in _clients:
        p = PROVIDERS[name]
        _clients[name] = _make_client(p.base_url, p.api_key, p.headers)
    return _clients[name]


async def probe(base_url: str, api_key: str = "", headers: dict[str, str] | None = None,
                title: str = "Provider") -> dict[str, Any]:
    """Check an endpoint answers /models with these credentials."""
    t0 = time.perf_counter()
    try:
        page = await _make_client(base_url, api_key, headers).with_options(max_retries=0).models.list()
        ids = [m.id.removeprefix("models/") for m in page.data]
    except Exception as e:
        msg = str(friendly_error(title, e))
        for secret in (api_key, *(headers or {}).values()):  # a draft's secrets aren't registered yet
            if secret and len(secret) >= 4:
                msg = msg.replace(secret, "***")
        return {"ok": False, "error": msg,
                "ms": round((time.perf_counter() - t0) * 1000)}
    return {"ok": True, "models": len(ids), "sample": sorted(ids)[:10],
            "ms": round((time.perf_counter() - t0) * 1000)}


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


def friendly_error(provider: str, e: Exception) -> ProviderError:
    """A user-facing error with every secret scrubbed out — provider error
    bodies sometimes echo (part of) the key or the request headers."""
    err = _friendly_error(provider, e)
    return err if isinstance(e, ProviderError) and err is e else ProviderError(vault.redact(str(err)))


def _friendly_error(provider: str, e: Exception) -> ProviderError:
    title = PROVIDERS[provider].title if provider in PROVIDERS else provider
    if isinstance(e, ProviderError):
        return e
    if isinstance(e, openai.RateLimitError):
        return ProviderError(
            f"{title} rate limit or free quota reached. Wait a minute and retry, or switch provider."
        )
    if isinstance(e, openai.AuthenticationError):
        return ProviderError(f"{title} rejected the API key. Check it in Settings → Providers (or .env).")
    if isinstance(e, openai.APITimeoutError):
        return ProviderError(f"{title} didn't respond in time. The model may be overloaded — retry, or pick another.")
    if isinstance(e, openai.APIStatusError) and e.status_code == 410:
        return ProviderError(f"{title} has retired this model. Pick another model in Configure → Generate.")
    if isinstance(e, openai.NotFoundError):
        return ProviderError(f"{title} doesn't recognise that model. Pick another in Configure.")
    if isinstance(e, openai.BadRequestError):
        return ProviderError(f"{title} rejected the request: {getattr(e, 'message', e)}")
    if isinstance(e, openai.APIConnectionError):
        return ProviderError(f"Can't reach {title}. Check your internet connection, the base URL, "
                             "and — for a local server — that it is running.")
    if isinstance(e, openai.APIStatusError):
        return ProviderError(f"{title} error {e.status_code}: {getattr(e, 'message', e)}")
    msg = str(e).strip() or type(e).__name__
    if "overload" in msg.lower() or "unavailable" in msg.lower():
        return ProviderError(f"{title} is temporarily overloaded. Retry in a moment, or switch provider.")
    return ProviderError(f"{title} call failed: {msg}")


# --- model listing ----------------------------------------------------------

_EXCLUDE_CHAT = ("embed", "rerank", "imagen", "veo", "tts", "aqa", "clip", "whisper",
                 "parse", "guard", "safety", "detector", "-image", "audio", "vision-only",
                 "dall-e", "moderation", "transcribe", "realtime")

_model_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}
_MODEL_TTL = 600


async def list_models(name: str, kind: str = "chat") -> list[str]:
    """Models the provider offers, filtered to chat or embedding models.
    Falls back to the configured default if listing fails."""
    p = get(name)
    fallback = [m for m in [p.default_model if kind == "chat" else p.default_embed_model] if m]
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
    p = get(name)
    configured = p.default_model if kind == "chat" else p.default_embed_model
    for m in (configured, *PREFERRED.get((name, kind), ())):
        if m in ids:
            return m
    return ids[0] if ids else configured


async def resolve_model(name: str, kind: str = "chat") -> str:
    """The model to use when none is chosen: the configured default if the
    provider still offers it, else the first preferred model it does offer."""
    models = await list_models(name, kind)
    if not models:
        what = "chat" if kind == "chat" else "embedding"
        raise ProviderError(f"{get(name).title} has no default {what} model and didn't list any. "
                            "Enter a model name in Configure, or set a default in Settings → Providers.")
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
