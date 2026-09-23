import httpx
import openai

from app.llm import provider as llm


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
    monkeypatch.setattr(llm.Provider, "default_model", property(lambda self: "retired/model"))
    listed = ["some/other", llm.PREFERRED[("nvidia", "chat")][1]]
    assert llm._pick_default("nvidia", "chat", listed) == llm.PREFERRED[("nvidia", "chat")][1]
    # Nothing preferred listed → first listed.
    assert llm._pick_default("nvidia", "chat", ["a/model"]) == "a/model"
