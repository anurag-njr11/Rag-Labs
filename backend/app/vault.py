"""Secrets at rest, and keeping them out of logs and error messages.

Encryption: AES-256-GCM. Each value gets a fresh 96-bit nonce and is bound to
where it is stored (`context`, e.g. "llm_providers:openai:api_key") as
associated data, so a ciphertext copied into another row or column fails to
decrypt instead of silently becoming that row's key. Stored form:
"enc:v1:<urlsafe-b64(nonce || ciphertext+tag)>".

The master key comes from, in order:
  1. RAGLABS_SECRET_KEY — 32 random bytes, urlsafe-base64 (generate with
     `python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`)
  2. a key file, created on first use with owner-only permissions, in the
     user's config directory — deliberately *not* next to the database, so a
     copied or leaked data/ directory doesn't carry the key that opens it.
     Override the location with RAGLABS_SECRET_KEY_FILE.

Losing the key makes stored API keys unreadable (they must be re-entered); it
never prevents the app from starting.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import secrets
import sys
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
_NONCE = 12


class VaultError(Exception):
    """A stored secret can't be decrypted (wrong key, or tampered with)."""


# --- master key -------------------------------------------------------------

_key: bytes | None = None
_key_lock = threading.Lock()


def default_key_file() -> Path:
    if env := os.environ.get("RAGLABS_SECRET_KEY_FILE"):
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "raglabs" / "secret.key"


def _decode_key(text: str, where: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
    except ValueError as e:
        raise RuntimeError(f"{where} is not valid base64.") from e
    if len(raw) != 32:
        raise RuntimeError(f"{where} must decode to exactly 32 bytes (got {len(raw)}).")
    return raw


def _read_or_create_key_file(path: Path) -> bytes:
    if path.exists():
        return _decode_key(path.read_text(encoding="ascii"), f"Key file {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    key = secrets.token_bytes(32)
    # O_EXCL: if another process created it meanwhile, use theirs instead.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _decode_key(path.read_text(encoding="ascii"), f"Key file {path}")
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(base64.urlsafe_b64encode(key).decode() + "\n")
    log.info("Created a new secret key at %s — back it up; stored API keys can't be read without it.", path)
    return key


def master_key() -> bytes:
    global _key
    with _key_lock:
        if _key is None:
            env = os.environ.get("RAGLABS_SECRET_KEY", "")
            _key = _decode_key(env, "RAGLABS_SECRET_KEY") if env else _read_or_create_key_file(default_key_file())
        return _key


def reset_key_cache() -> None:
    """Forget the loaded master key (tests, key rotation)."""
    global _key
    with _key_lock:
        _key = None


# --- encrypt / decrypt ------------------------------------------------------


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)  # type: ignore[union-attr]


def encrypt(plaintext: str, context: str) -> str:
    """Encrypt `plaintext` bound to `context`. Empty stays empty (nothing to hide)."""
    if not plaintext:
        return ""
    nonce = secrets.token_bytes(_NONCE)
    ct = AESGCM(master_key()).encrypt(nonce, plaintext.encode(), context.encode())
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(token: str, context: str) -> str:
    if not token:
        return ""
    if not is_encrypted(token):
        raise VaultError("value is not encrypted")
    try:
        blob = base64.urlsafe_b64decode(token[len(PREFIX):])
        pt = AESGCM(master_key()).decrypt(blob[:_NONCE], blob[_NONCE:], context.encode())
    except (InvalidTag, ValueError) as e:
        raise VaultError("can't decrypt — the secret key changed, or the value was altered") from e
    return pt.decode()


# --- redaction --------------------------------------------------------------

# Shapes of common provider credentials, caught even when we don't know the value.
_KEY_PATTERNS = re.compile(
    r"(?:"
    r"sk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_\-]{16,}"   # OpenAI / Anthropic / OpenRouter
    r"|AIza[0-9A-Za-z_\-]{30,}"                        # Google
    r"|nvapi-[A-Za-z0-9_\-]{20,}"                      # NVIDIA
    r"|gsk_[A-Za-z0-9]{20,}"                           # Groq
    r"|(?<=Bearer )[A-Za-z0-9._\-~+/]{12,}=*"          # any bearer token
    r")"
)
_SENSITIVE_QUERY = {"key", "api_key", "api-key", "apikey", "token", "access_token", "auth", "sig",
                    "signature", "secret", "password", "code", "x-api-key"}

_known: Callable[[], Iterable[str]] = lambda: ()


def register_known_secrets(fn: Callable[[], Iterable[str]]) -> None:
    """`fn` returns the secret values currently configured (API keys, header values)."""
    global _known
    _known = fn


def redact(text: str) -> str:
    """Replace every configured secret and anything shaped like a credential with ***."""
    if not text:
        return text
    for s in sorted({s for s in _known() if s and len(s) >= 6}, key=len, reverse=True):
        text = text.replace(s, "***")
    text = _KEY_PATTERNS.sub("***", text)
    return re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1***@", text)


def url_has_credentials(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.password or parts.username:
        return True
    return any(k.lower() in _SENSITIVE_QUERY for k, _ in parse_qsl(parts.query, keep_blank_values=True))


def redact_url(url: str) -> str:
    """The URL with user:password and credential-looking query values masked."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact(url)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "***@" + netloc.rsplit("@", 1)[1]
    query = urlencode([(k, "***" if k.lower() in _SENSITIVE_QUERY else v)
                       for k, v in parse_qsl(parts.query, keep_blank_values=True)], safe="*")
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


class RedactingFilter(logging.Filter):
    """Scrubs secrets from every log record before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 — a broken record shouldn't break logging
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[1] is not None:
            # Tracebacks are formatted later from exc_info; render and scrub them now.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def install_log_redaction() -> None:
    f = RedactingFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "httpx", "openai"):
        lg = logging.getLogger(name)
        if not any(isinstance(x, RedactingFilter) for x in lg.filters):
            lg.addFilter(f)
        for h in lg.handlers:
            if not any(isinstance(x, RedactingFilter) for x in h.filters):
                h.addFilter(f)
