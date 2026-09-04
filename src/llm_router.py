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


def _log_call(provider, model, tier, ok, note=""):
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

def call_groq(prompt, model="llama-3.1-8b-instant"):
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


def call_gemini(prompt, model="gemini-1.5-flash"):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    resp = requests.post(
        url,
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("gemini rate limited")
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_cerebras(prompt, model="llama3.1-8b"):
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


def call_openrouter(prompt, model="meta-llama/llama-3.1-8b-instruct:free"):
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
    ("groq", call_groq, "llama-3.1-8b-instant"),
    ("cerebras", call_cerebras, "llama3.1-8b"),
    ("gemini", call_gemini, "gemini-1.5-flash"),
    ("openrouter", call_openrouter, "meta-llama/llama-3.1-8b-instruct:free"),
]

EXTRACT_TIER = [
    ("gemini", call_gemini, "gemini-1.5-flash"),
    ("groq", call_groq, "llama-3.1-70b-versatile"),
    ("openrouter", call_openrouter, "meta-llama/llama-3.1-8b-instruct:free"),
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
