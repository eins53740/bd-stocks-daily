"""
Unit tests for v4 Phase G — llm_client.py.

Pure helpers (resolve_key, extract_json) + complete_json's provider-fallback
logic with the SDK calls monkeypatched — no network, no real keys, uv-safe.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import llm_client as lc  # noqa: E402


# ------------------------- resolve_key -------------------------
def test_resolve_key_env_wins(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key")
    assert lc.resolve_key("api_key_groq", "GROQ_API_KEY", {"api_key_groq": "file-key"}) == "env-key"


def test_resolve_key_falls_back_to_file(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert lc.resolve_key("api_key_groq", "GROQ_API_KEY", {"api_key_groq": "file-key"}) == "file-key"


def test_resolve_key_none_when_absent(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert lc.resolve_key("api_key_gemini", "GEMINI_API_KEY", {}) is None
    assert lc.resolve_key("api_key_gemini", "GEMINI_API_KEY", None) is None


# ------------------------- extract_json -------------------------
def test_extract_json_plain():
    assert lc.extract_json('{"conviction_0_100": 72, "verdict": "buy"}')["conviction_0_100"] == 72


def test_extract_json_fenced():
    txt = "Here is my answer:\n```json\n{\"verdict\": \"hold\", \"conviction_0_100\": 55}\n```\nThanks!"
    assert lc.extract_json(txt)["verdict"] == "hold"


def test_extract_json_prose_wrapped():
    txt = 'The stock looks fair. {"verdict":"neutral","conviction_0_100":50} — that is my read.'
    assert lc.extract_json(txt)["conviction_0_100"] == 50


def test_extract_json_broken_and_nondict():
    assert lc.extract_json("not json at all") is None
    assert lc.extract_json("") is None
    assert lc.extract_json("[1,2,3]") is None  # list is not a dict


# ------------------------- complete_json fallback -------------------------
def test_complete_json_groq_success(monkeypatch):
    monkeypatch.setattr(lc, "_call_groq", lambda *a, **k: '{"conviction_0_100": 80}')
    out = lc.complete_json("p", "s", keys={"api_key_groq": "x"})
    assert out["ok"] and out["provider"] == "groq" and out["data"]["conviction_0_100"] == 80


def test_complete_json_falls_back_to_gemini_on_groq_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("groq down")
    monkeypatch.setattr(lc, "_call_groq", boom)
    monkeypatch.setattr(lc, "_call_gemini", lambda *a, **k: '{"conviction_0_100": 60}')
    out = lc.complete_json("p", "s", keys={"api_key_groq": "x", "api_key_gemini": "y"})
    assert out["ok"] and out["provider"] == "gemini" and out["data"]["conviction_0_100"] == 60


def test_complete_json_falls_back_on_unparseable_groq(monkeypatch):
    monkeypatch.setattr(lc, "_call_groq", lambda *a, **k: "sorry, no JSON here")
    monkeypatch.setattr(lc, "_call_gemini", lambda *a, **k: '{"v": 1}')
    out = lc.complete_json("p", None, keys={"api_key_groq": "x", "api_key_gemini": "y"})
    assert out["ok"] and out["provider"] == "gemini"


def test_complete_json_no_keys_degrades(monkeypatch):
    out = lc.complete_json("p", None, keys={})
    assert out["ok"] is False and out["provider"] is None and out["data"] is None
    assert "no key" in out["error"]


def test_complete_json_groq_missing_gemini_present(monkeypatch):
    monkeypatch.setattr(lc, "_call_gemini", lambda *a, **k: '{"conviction_0_100": 42}')
    out = lc.complete_json("p", None, keys={"api_key_gemini": "y"})  # no groq key
    assert out["ok"] and out["provider"] == "gemini" and out["data"]["conviction_0_100"] == 42
