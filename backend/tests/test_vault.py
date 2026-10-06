"""Secrets at rest and in transit to logs, errors and exports."""

import base64
import logging
import os
import secrets
import stat

import httpx
import openai
import pytest
from test_provider import clean_env  # noqa: F401  (fixture)

from app import db, vault
from app.llm import provider as llm
from app.nodes import generate  # noqa: F401  (registers Generate types)


def _new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


# --- vault primitives ---------------------------------------------------------

def test_round_trip_and_fresh_nonce():
    a = vault.encrypt("sk-secret-value", "ctx")
    b = vault.encrypt("sk-secret-value", "ctx")
    assert a.startswith(vault.PREFIX) and a != b  # random nonce per value
    assert "sk-secret-value" not in a
    assert vault.decrypt(a, "ctx") == "sk-secret-value"


def test_ciphertext_is_bound_to_its_context():
    token = vault.encrypt("k", "llm_providers:openai:api_key")
    with pytest.raises(vault.VaultError):
        vault.decrypt(token, "llm_providers:evil:api_key")


def test_wrong_key_and_tampering_fail_cleanly(monkeypatch):
    token = vault.encrypt("k", "ctx")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(vault.VaultError):
        vault.decrypt(tampered, "ctx")
    monkeypatch.setenv("RAGLABS_SECRET_KEY", _new_key())
    vault.reset_key_cache()
    with pytest.raises(vault.VaultError):
        vault.decrypt(token, "ctx")


def test_key_file_is_created_owner_only(tmp_path):
    path = tmp_path / "secret.key"
    assert not path.exists()
    vault.encrypt("x", "ctx")
    assert path.exists()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    vault.reset_key_cache()
    assert vault.master_key() == base64.urlsafe_b64decode(path.read_text().strip())


def test_malformed_env_key_is_rejected(monkeypatch):
    monkeypatch.setenv("RAGLABS_SECRET_KEY", "dG9vLXNob3J0")  # base64 of "too-short"
    vault.reset_key_cache()
    with pytest.raises(RuntimeError, match="32 bytes"):
        vault.master_key()


# --- redaction ------------------------------------------------------------------

def test_redacts_known_and_credential_shaped_values(monkeypatch):
    monkeypatch.setattr(vault, "_known", lambda: ["custom-secret-123"])
    text = ("auth failed for custom-secret-123, sk-proj-abcdefghijklmnopqrstu, "
            "AIzaSyA1234567890abcdefghijklmnopqrstu, Bearer abcdef1234567890, "
            "https://bob:hunter2@gw.example/v1")
    out = vault.redact(text)
    for leaked in ("custom-secret-123", "sk-proj-abc", "AIzaSy", "abcdef1234567890", "hunter2"):
        assert leaked not in out


def test_redact_url():
    assert vault.redact_url("https://u:p@h.example/v1?api-version=1&key=abc") == \
        "https://***@h.example/v1?api-version=1&key=***"
    assert vault.url_has_credentials("https://h/v1?api_key=x")
    assert not vault.url_has_credentials("https://h/v1?api-version=2024-10-01")


def test_log_records_are_scrubbed(monkeypatch, caplog):
    monkeypatch.setattr(vault, "_known", lambda: ["very-secret-key-42"])
    lg = logging.getLogger("test.vault")
    lg.addFilter(vault.RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.vault"):
        lg.info("calling with %s", "very-secret-key-42")
        try:
            raise ValueError("boom very-secret-key-42")
        except ValueError:
            lg.exception("failed")
    assert "very-secret-key-42" not in caplog.text
    assert "***" in caplog.text


def test_provider_errors_never_echo_the_key(clean_env):  # noqa: F811
    clean_env.setenv("OPENAI_API_KEY", "sk-live-0123456789abcdefXYZ")
    llm.refresh()
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    err = openai.BadRequestError("Invalid key sk-live-0123456789abcdefXYZ",
                                 response=httpx.Response(400, request=req), body=None)
    assert "sk-live-0123456789abcdefXYZ" not in str(llm.friendly_error("openai", err))


def test_provider_repr_hides_secrets():
    p = llm.Provider(name="x1", title="X", base_url="http://x", api_key="sk-hidden-1234",
                     headers={"X-Token": "tok-hidden"})
    assert "sk-hidden-1234" not in repr(p) and "tok-hidden" not in repr(p)


def test_public_view_masks_url_credentials():
    p = llm.Provider(name="x1", title="X", base_url="https://u:pw@gw.example/v1?key=abc")
    assert "pw" not in p.public()["base_url"] and "abc" not in p.public()["base_url"]


# --- storage ----------------------------------------------------------------------

async def _raw_row(name: str) -> dict:
    return await db.fetch_one("SELECT api_key, headers FROM llm_providers WHERE name=?", (name,))


async def test_keys_and_headers_are_encrypted_in_the_database(clean_env, database):  # noqa: F811
    await llm.load()
    await llm.save("acme", {"base_url": "https://llm.acme.test/v1", "api_key": "acme-key-0001",
                            "headers": {"X-Org": "org-secret-77"}})
    raw = await _raw_row("acme")
    assert raw["api_key"].startswith(vault.PREFIX) and raw["headers"].startswith(vault.PREFIX)
    assert "acme-key-0001" not in str(raw) and "org-secret-77" not in str(raw)
    llm._db_rows.clear()
    await llm.load()
    p = llm.get("acme")
    assert p.api_key == "acme-key-0001" and p.headers == {"X-Org": "org-secret-77"}


async def test_plaintext_rows_are_migrated_on_load(clean_env, database):  # noqa: F811
    async with db.tx() as c:
        await c.execute("INSERT INTO llm_providers (name, base_url, api_key, headers, created_at, updated_at)"
                        " VALUES ('old', 'http://old/v1', 'legacy-plain-key', '{\"X-A\": \"legacy-hdr\"}', 'x', 'x')")
    await llm.load()
    raw = await _raw_row("old")
    assert raw["api_key"].startswith(vault.PREFIX) and "legacy-plain-key" not in str(raw)
    assert llm.get("old").api_key == "legacy-plain-key"


async def test_undecryptable_key_disables_provider_without_crashing(clean_env, database):  # noqa: F811
    await llm.load()
    await llm.save("acme", {"base_url": "https://llm.acme.test/v1", "api_key": "acme-key-0001",
                            "key_required": True})
    stored = (await _raw_row("acme"))["api_key"]
    clean_env.setenv("RAGLABS_SECRET_KEY", _new_key())  # the key was lost / rotated
    vault.reset_key_cache()
    await llm.load()
    ok, reason = llm.availability("acme")
    assert not ok and "decrypt" in reason
    # Editing other fields keeps the old ciphertext rather than wiping it.
    await llm.save("acme", {"default_model": "m"})
    assert (await _raw_row("acme"))["api_key"] == stored
    # Re-entering the key fixes it.
    await llm.save("acme", {"api_key": "acme-key-0002"})
    assert llm.availability("acme")[0] and llm.get("acme").api_key == "acme-key-0002"


async def test_changing_base_url_requires_reentering_the_key(clean_env, database):  # noqa: F811
    await llm.load()
    await llm.save("acme", {"base_url": "https://llm.acme.test/v1", "api_key": "acme-key-0001"})
    with pytest.raises(llm.ProviderError, match="Re-enter"):
        await llm.save("acme", {"base_url": "https://attacker.example/v1"})
    assert llm.get("acme").base_url == "https://llm.acme.test/v1"
    await llm.save("acme", {"base_url": "https://llm2.acme.test/v1", "api_key": "acme-key-0001"})


async def test_credentials_in_base_url_are_refused(clean_env, database):  # noqa: F811
    await llm.load()
    with pytest.raises(llm.ProviderError, match="not in the base URL"):
        await llm.save("acme", {"base_url": "https://u:p@llm.acme.test/v1"})


async def test_draft_test_never_sends_stored_key_elsewhere(clean_env, database, monkeypatch):  # noqa: F811
    from app.api import system
    from app.api.system import ProviderIn

    await llm.load()
    await llm.save("acme", {"base_url": "https://llm.acme.test/v1", "api_key": "acme-key-0001"})
    sent = {}

    async def fake_probe(base_url, api_key="", headers=None, title=""):
        sent.update(base_url=base_url, api_key=api_key)
        return {"ok": True, "ms": 0}

    monkeypatch.setattr(llm, "probe", fake_probe)
    await system.test_draft_provider(ProviderIn(name="acme", base_url="https://attacker.example/v1"))
    assert sent["api_key"] == ""
    await system.test_draft_provider(ProviderIn(name="acme"))
    assert sent["api_key"] == "acme-key-0001"
