"""
llm_router.py

One function to call an LLM, tries multiple FREE providers in order,
falls to the next one automatically if a provider is rate-limited or errors out.

Two tiers:
  - FILTER tier: cheap/fast models, used for the "is this worth reading? y/n" pass.
  - EXTRACT tier: slightly better models, used only on articles that passed the filter.

This keeps token usage low: most articles get killed by the cheap filter,
only the interesting ones reach the better model.

Add your free API keys as environment variables (locally in a .env file,
or as GitHub Actions secrets when running in CI). None of these providers
require a credit card for their free tier as of writing -- if that changes,
just swap the provider list below.
"""

import os
import time
import json
import requests

CALL_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "research", "_call_log.jsonl")


import re

def _scrub_secrets(text):
    """Defense in depth: strip anything that looks like a key=... or apikey=... query param
    before it ever gets written to a file, in case a future provider's error text embeds one."""
    if not text:
        return text
    return re.sub(r'([?&](?:key|apikey|api_key|token)=)[^&\s"\']+', r'\1***REDACTED***', text, flags=re.IGNORECASE)


def _log_call(provider, model, tier, ok, note=""):
    note = _scrub_secrets(str(note))
    os.makedirs(os.path.dirname(CALL_LOG_PATH), exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "model": model,
        "tier": tier,
        "ok": ok,
        "note": note,
    }
    with open(CALL_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------- Individual provider callers ----------
# Each function takes a prompt string, returns text, or raises an Exception on failure.

def call_groq(prompt, model="openai/gpt-oss-20b"):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("no GROQ_API_KEY set")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("groq rate limited")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


_gemini_model_cache = {"name": None}


def _get_gemini_model():
    """
    Asks Gemini's own API which models currently exist and support generateContent,
    picks a Flash model (fast + free-tier eligible), and caches it for this run.
    This avoids hardcoding a model name that Google can rename or roll out unevenly.
    Falls back to a hardcoded guess if the listing call itself fails.
    """
    if _gemini_model_cache["name"]:
        return _gemini_model_cache["name"]

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return "gemini-2.0-flash"  # will fail downstream with a clear "no key" error anyway

    try:
        resp = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=15,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"gemini model list HTTP {resp.status_code}")
        models = resp.json().get("models", [])
        # Prefer models with "flash" in the name that support generateContent, not "flash-lite" or "-tts"/"-image"
        candidates = [
            m["name"].replace("models/", "")
            for m in models
            if "generateContent" in m.get("supportedGenerationMethods", [])
            and "flash" in m.get("name", "").lower()
            and "lite" not in m.get("name", "").lower()
            and "tts" not in m.get("name", "").lower()
            and "image" not in m.get("name", "").lower()
        ]
        if candidates:
            # Sort so newest-looking version string comes first (crude but works: e.g. gemini-3-flash > gemini-2.0-flash)
            candidates.sort(reverse=True)
            _gemini_model_cache["name"] = candidates[0]
            return candidates[0]
    except Exception as e:
        print(f"[warn] could not list Gemini models, falling back to hardcoded name: {e}")

    _gemini_model_cache["name"] = "gemini-2.0-flash"
    return "gemini-2.0-flash"


def call_gemini(prompt, model=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY set")
    if model is None:
        model = _get_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    try:
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        # Never let the raw exception (which embeds the URL, and therefore the key) get logged
        raise RuntimeError(f"gemini request failed (network-level, model={model})")

    if resp.status_code == 429:
        raise RuntimeError("gemini rate limited")
    if resp.status_code == 404:
        # Model may have just been renamed again -- clear cache so the next call re-discovers it
        _gemini_model_cache["name"] = None
        raise RuntimeError(f"gemini 404 for model '{model}' -- cache cleared, will rediscover next call")
    if resp.status_code >= 400:
        # Build our own error message from status code only -- never call resp.raise_for_status()
        # here, since its exception text includes the full request URL (and therefore the key).
        raise RuntimeError(f"gemini HTTP {resp.status_code} for model '{model}'")
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_cerebras(prompt, model="gpt-oss-120b"):
    key = os.environ.get("CEREBRAS_API_KEY")
    if not key:
        raise RuntimeError("no CEREBRAS_API_KEY set")
    resp = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("cerebras rate limited")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_openrouter(prompt, model="openrouter/free"):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("no OPENROUTER_API_KEY set")
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("openrouter rate limited")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ---------- Tiers: order = preference. First one that works, wins. ----------
# Edit these lists freely -- add/remove providers, reorder them, swap models.

FILTER_TIER = [
    ("groq", call_groq, "openai/gpt-oss-20b"),
    ("gemini", call_gemini, None),  # None = auto-discover current model, see _get_gemini_model()
    ("openrouter", call_openrouter, "openrouter/free"),
    ("cerebras", call_cerebras, "gpt-oss-120b"),  # free tier here has been unstable lately, kept as last resort
]

EXTRACT_TIER = [
    ("gemini", call_gemini, None),
    ("groq", call_groq, "openai/gpt-oss-120b"),
    ("openrouter", call_openrouter, "openrouter/free"),
    ("cerebras", call_cerebras, "gpt-oss-120b"),
]


def call_llm(prompt, tier="filter"):
    """
    Tries each provider in the chosen tier in order.
    Returns (text, provider_name) on success.
    Raises RuntimeError if every provider in the tier fails.
    """
    chain = FILTER_TIER if tier == "filter" else EXTRACT_TIER
    last_err = None
    for provider_name, fn, model in chain:
        try:
            text = fn(prompt, model=model)
            _log_call(provider_name, model, tier, ok=True)
            return text, provider_name
        except Exception as e:
            _log_call(provider_name, model, tier, ok=False, note=str(e))
            last_err = e
            continue
    raise RuntimeError(f"All providers in '{tier}' tier failed. Last error: {last_err}")
