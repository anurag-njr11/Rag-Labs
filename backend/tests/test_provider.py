import json

import httpx
import openai
import pytest

from app.core.node import slot_types
from app.core.pipeline import recommended_pipeline, validate_pipeline
from app.llm import provider as llm
from app.nodes import generate  # noqa: F401  (registers Generate types)


@pytest.fixture
def clean_env(monkeypatch):
    """No provider keys from the developer's shell or .env leak into a test."""
    for p in llm.PRESETS:
        for suffix in ("API_KEY", "BASE_URL", "DEFAULT_MODEL", "DEFAULT_EMBED_MODEL"):
            monkeypatch.delenv(f"{llm.env_prefix(p)}_{suffix}", raising=False)
    monkeypatch.delenv("LLM_PROVIDERS", raising=False)
    monkeypatch.setattr(llm, "_env", lambda key: __import__("os").environ.get(key, ""))
    llm._db_rows.clear()
    llm.refresh()
    yield monkeypatch
    llm._db_rows.clear()
    monkeypatch.undo()
    llm.refresh()


def _status_error(code: int) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    return openai.APIStatusError("gone", response=httpx.Response(code, request=req), body=None)


def test_retired_model_message():
    msg = str(llm.friendly_error("nvidia", _status_error(410)))
    assert "retired" in msg and "Configure" in msg


def test_overloaded_message():
    assert "temporarily overloaded" in str(llm.friendly_error("nvidia", Exception("Service temporarily overloaded")))


def test_default_falls_back_when_configured_model_is_gone(monkeypatch):
    # Configured default missing from the catalog → first preferred model that is listed.
    monkeypatch.setitem(llm.PROVIDERS, "nvidia", llm.Provider(name="nvidia", title="NVIDIA", base_url="x",
                                                              default_model="retired/model", preset="nvidia"))
    listed = ["some/other", llm.PREFERRED[("nvidia", "chat")][1]]
    assert llm._pick_default("nvidia", "chat", listed) == llm.PREFERRED[("nvidia", "chat")][1]
    # Nothing preferred listed → first listed.
    assert llm._pick_default("nvidia", "chat", ["a/model"]) == "a/model"


def test_only_pinned_presets_offered_by_default(clean_env):
    assert set(llm.PROVIDERS) == {"gemini", "nvidia"}
    assert set(slot_types("generate")) == {"gemini", "nvidia"}
    assert not llm.availability("gemini")[0]


def test_env_key_enables_a_preset(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "sk-test-1234567890")
    llm.refresh()
    assert llm.availability("openai") == (True, "")
    assert "openai" in slot_types("generate")
    # OpenAI doesn't take reasoning_effort="none" on every model → send nothing by default.
    cfg = validate_pipeline({**recommended_pipeline(), "generate": {"type": "openai"}})
    assert cfg["generate"]["reasoning_effort"] == "default"
    assert recommended_pipeline()["generate"]["type"] == "openai"


def test_env_overrides_base_url_and_model(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "k" * 12)
    clean_env.setenv("GEMINI_BASE_URL", "https://proxy.example/v1")
    clean_env.setenv("GEMINI_DEFAULT_MODEL", "gemini-x")
    llm.refresh()
    p = llm.get("gemini")
    assert (p.base_url, p.default_model, p.source) == ("https://proxy.example/v1", "gemini-x", "env")


def test_custom_providers_from_env_json(clean_env):
    clean_env.setenv("MYVLLM_TOKEN", "tok-abcdefgh")
    clean_env.setenv("LLM_PROVIDERS", json.dumps([
        {"name": "myvllm", "title": "My vLLM", "base_url": "http://gpu:8000/v1",
         "api_key_env": "MYVLLM_TOKEN", "default_model": "qwen3"},
        {"name": "Bad Name", "base_url": "http://x"},  # ignored
    ]))
    llm.refresh()
    p = llm.get("myvllm")
    assert p.custom and p.api_key == "tok-abcdefgh" and p.default_model == "qwen3"
    assert llm.availability("myvllm")[0]
    assert "Bad Name" not in llm.PROVIDERS


def test_local_preset_needs_no_key_once_enabled(clean_env):
    assert "ollama" not in llm.PROVIDERS  # not offered until enabled
    clean_env.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    llm.refresh()
    assert llm.availability("ollama") == (True, "")


def test_public_view_never_contains_the_key(clean_env):
    p = llm.Provider(name="x1", title="X", base_url="http://x", api_key="sk-secret-9876")
    pub = p.public()
    assert "sk-secret-9876" not in json.dumps(pub)
    assert pub["key_set"] and pub["key_hint"] == "…9876"


async def test_ui_saved_provider_round_trip(clean_env, database):
    await llm.load()
    p = await llm.save("acme", {"title": "Acme Gateway", "base_url": "https://llm.acme.test/v1",
                                "api_key": "acme-key-0001", "default_model": "acme-large"})
    assert p.source == "custom-ui" and "acme" in slot_types("generate")
    # An empty key on edit keeps the stored one.
    await llm.save("acme", {"api_key": "", "default_model": "acme-small"})
    llm._db_rows.clear()
    await llm.load()  # survives a restart
    p = llm.get("acme")
    assert (p.api_key, p.default_model) == ("acme-key-0001", "acme-small")
    await llm.remove("acme")
    assert "acme" not in llm.PROVIDERS and "acme" not in slot_types("generate")


async def test_ui_key_for_preset_overrides_env(clean_env, database):
    clean_env.setenv("GROQ_API_KEY", "env-key-aaaa")
    await llm.load()
    await llm.save("groq", {"api_key": "ui-key-bbbb"})
    assert llm.get("groq").api_key == "ui-key-bbbb"
    await llm.remove("groq")
    assert llm.get("groq").api_key == "env-key-aaaa"  # falls back to .env


async def test_custom_provider_requires_base_url(clean_env, database):
    await llm.load()
    with pytest.raises(llm.ProviderError):
        await llm.save("nourl", {"api_key": "k"})
    with pytest.raises(llm.ProviderError):
        await llm.save("Bad Name", {"base_url": "http://x"})


def test_unknown_provider_is_a_friendly_error(clean_env):
    with pytest.raises(llm.ProviderError, match="Settings"):
        llm.client("nope")


async def test_retrying_backs_off_only_on_retryable_errors():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise llm.ProviderError("rate limit", retryable=True)
        return "ok"

    assert await llm.retrying(flaky, base_s=0) == "ok" and len(calls) == 3

    async def bad_key():
        calls.append(1)
        raise llm.ProviderError("rejected the API key")

    calls.clear()
    with pytest.raises(llm.ProviderError):
        await llm.retrying(bad_key, base_s=0)
    assert len(calls) == 1  # not retried

    async def always():
        raise llm.ProviderError("overloaded", retryable=True)

    with pytest.raises(llm.ProviderError):
        await llm.retrying(always, attempts=2, base_s=0)


def test_rate_limit_errors_are_retryable():
    import httpx
    import openai

    resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    err = llm.friendly_error("nvidia", openai.RateLimitError("slow down", response=resp, body=None))
    assert err.retryable
    resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    assert not llm.friendly_error("nvidia", openai.AuthenticationError("no", response=resp, body=None)).retryable
