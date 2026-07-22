"""
llm_client.py — v4 Phase G: a small, reusable Groq→Gemini JSON client.

One entry point, `complete_json(prompt, system)`, that asks an independent model
(Groq primary → Gemini fallback) for a strict-JSON answer and returns a parsed
dict — never raises. Used by second_opinion.py (the 3-persona opinion panel) and
reusable by later phases (H sentiment).

Keys are read the skill-wide way: env var first (`GROQ_API_KEY` / `GEMINI_API_KEY`),
then `api_key_groq` / `api_key_gemini` from `BD_Finance\config\api_keys.txt` via the
existing `api_keys_reader` (gitignored — no secret ever lives in this repo). A
missing key or provider error degrades: Groq→Gemini→`{"ok": false, ...}`.

Runs under ambient Python312 (the `groq` and `google.generativeai` SDKs live there,
not in the skill's uv venv). SDKs are imported lazily inside the call path so the
pure helpers (`resolve_key`, `extract_json`) unit-test under uv with no SDK present.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"
GEMINI_MODEL_DEFAULT = "gemini-2.0-flash"

BD_FINANCE = Path(r"C:\Github\BD\Finance\BD_Finance")
API_KEYS_PATH = BD_FINANCE / "config" / "api_keys.txt"


def log(msg: str) -> None:
    print(f"[llm_client] {msg}", file=sys.stderr)


# ===================================================================
# Pure helpers (stdlib only — unit-tested under uv)
# ===================================================================
def resolve_key(name: str, env_var: str, keys_dict: dict | None) -> str | None:
    """Env var first (ops override), then the api_keys.txt value. None if neither."""
    env = os.environ.get(env_var)
    if env:
        return env
    if isinstance(keys_dict, dict):
        v = keys_dict.get(name)
        if v:
            return v
    return None


def extract_json(text: str) -> dict | None:
    """Best-effort parse of a JSON object out of a model reply. Handles ```json
    fences, leading/trailing prose, and a single balanced {...}. None on failure."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    # Fast path: the whole thing is JSON.
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Otherwise take the first balanced object (good enough for terse LLM JSON;
    # braces inside string values are rare in these short replies).
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def load_keys() -> dict:
    """api_keys.txt as a name→value dict via the shared reader; {} on any problem."""
    try:
        if str(BD_FINANCE) not in sys.path:
            sys.path.insert(0, str(BD_FINANCE))
        from api_keys_reader import api_keys_reader
        return api_keys_reader(str(API_KEYS_PATH)) or {}
    except Exception as e:
        log(f"could not read api_keys.txt: {type(e).__name__}: {e}")
        return {}


# ===================================================================
# Provider calls (lazy SDK imports — ambient Python only)
# ===================================================================
def _call_groq(prompt: str, system: str | None, model: str,
               max_tokens: int, temperature: float, key: str) -> str:
    from groq import Groq
    client = Groq(api_key=key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens,
        temperature=temperature, response_format={"type": "json_object"})
    return resp.choices[0].message.content


def _call_gemini(prompt: str, system: str | None, model: str,
                 max_tokens: int, temperature: float, key: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=key)
    gm = genai.GenerativeModel(model, system_instruction=system or None)
    resp = gm.generate_content(prompt, generation_config={
        "response_mime_type": "application/json",
        "max_output_tokens": max_tokens, "temperature": temperature})
    return resp.text


# ===================================================================
# Public entry point
# ===================================================================
def complete_json(prompt: str, system: str | None = None, *,
                  groq_model: str = GROQ_MODEL_DEFAULT,
                  gemini_model: str = GEMINI_MODEL_DEFAULT,
                  max_tokens: int = 400, temperature: float = 0.4,
                  keys: dict | None = None) -> dict:
    """Ask Groq (then Gemini) for a JSON object. Never raises.

    Returns {ok, provider, model, data|None, error|None}. `keys` is injectable
    for tests; otherwise loaded from api_keys.txt."""
    keys = keys if keys is not None else load_keys()
    errors: list[str] = []

    gk = resolve_key("api_key_groq", "GROQ_API_KEY", keys)
    if gk:
        try:
            data = extract_json(_call_groq(prompt, system, groq_model, max_tokens, temperature, gk))
            if data is not None:
                return {"ok": True, "provider": "groq", "model": groq_model, "data": data, "error": None}
            errors.append("groq: unparseable JSON")
        except Exception as e:
            errors.append(f"groq: {type(e).__name__}: {e}")
    else:
        errors.append("groq: no key")

    ek = resolve_key("api_key_gemini", "GEMINI_API_KEY", keys)
    if ek:
        try:
            data = extract_json(_call_gemini(prompt, system, gemini_model, max_tokens, temperature, ek))
            if data is not None:
                return {"ok": True, "provider": "gemini", "model": gemini_model, "data": data, "error": None}
            errors.append("gemini: unparseable JSON")
        except Exception as e:
            errors.append(f"gemini: {type(e).__name__}: {e}")
    else:
        errors.append("gemini: no key")

    return {"ok": False, "provider": None, "model": None, "data": None, "error": "; ".join(errors)}
