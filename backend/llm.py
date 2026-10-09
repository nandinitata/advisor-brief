"""Text generation behind one function, two providers, both open-weights.

  AB_LLM_PROVIDER=ollama   local dev, llama3 via Ollama (default when no Groq key)
  AB_LLM_PROVIDER=groq     hosted Llama via Groq (fast; used for the demo)

Groq is still an open-weights model (Meta's Llama), just served fast enough for a
live demo. Set GROQ_API_KEY to use it. Embeddings are handled separately by the
vector store's own on-device model (see ingest.py), so nothing here needs an
embedding endpoint and the backend deploys without Ollama.

Two tiers, for Inference FinOps (see router.py): a *small* model for cheap,
mechanical tasks and a *large* one for real writing. `generate(..., tier=...)`
picks the model; pass a `meter` list and each call appends its token usage to it
so the agent can price the run.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests


def _load_env() -> None:
    """Tiny .env loader (no dependency): KEY=VALUE lines into os.environ."""
    env = Path(__file__).parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env()

_PROVIDER = os.environ.get("AB_LLM_PROVIDER") or ("groq" if os.environ.get("GROQ_API_KEY") else "ollama")

OLLAMA_MODEL = os.environ.get("AB_OLLAMA_MODEL", "llama3")
OLLAMA_SMALL_MODEL = os.environ.get("AB_OLLAMA_SMALL_MODEL", OLLAMA_MODEL)
GROQ_MODEL = os.environ.get("AB_GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_SMALL_MODEL = os.environ.get("AB_GROQ_SMALL_MODEL", "openai/gpt-oss-20b")
OLLAMA_CTX = int(os.environ.get("AB_OLLAMA_CTX", "8192"))

# the model used per tier, for the configured provider
_LARGE = GROQ_MODEL if _PROVIDER == "groq" else OLLAMA_MODEL
_SMALL = GROQ_SMALL_MODEL if _PROVIDER == "groq" else OLLAMA_SMALL_MODEL

# names surfaced on /health. The writer (and reviser) run on the large tier; the
# planner and the compliance judge run small. See router._TASK_TIER.
WRITER_MODEL = _LARGE
JUDGE_MODEL = _SMALL
SMALL_MODEL = _SMALL
LARGE_MODEL = _LARGE


def provider() -> str:
    return _PROVIDER


def model_for(tier: str) -> str:
    return _SMALL if tier == "small" else _LARGE


def _est_tokens(text: str) -> int:
    """Rough token count when the provider doesn't report usage (Ollama). ~4 chars/token."""
    return max(1, len(text) // 4)


def _meter(meter: list | None, tier: str, model: str, pt: int, ct: int) -> None:
    if meter is not None:
        meter.append({"tier": tier, "model": model, "in": pt, "out": ct})


def _ollama(system: str, user: str, temperature: float, model: str, tier: str, meter: list | None) -> str:
    from langchain_ollama import ChatOllama

    chat = ChatOllama(model=model, temperature=temperature, num_ctx=OLLAMA_CTX)
    resp = chat.invoke([("system", system), ("human", user)])
    text = (resp.content or "").strip()
    _meter(meter, tier, model, _est_tokens(system + user), _est_tokens(text))  # estimated
    return text


def _groq(system: str, user: str, temperature: float, model: str, tier: str, meter: list | None) -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set but provider is groq.")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=90,
    )
    resp.raise_for_status()
    body = resp.json()
    usage = body.get("usage") or {}
    _meter(meter, tier, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return body["choices"][0]["message"]["content"].strip()


def generate(
    system: str,
    user: str,
    temperature: float = 0.2,
    tier: str = "large",
    meter: list | None = None,
) -> str:
    """One-shot system+user completion on the given tier's model.

    Pass `meter` (a list) to capture this call's token usage for FinOps."""
    model = model_for(tier)
    if _PROVIDER == "groq":
        return _groq(system, user, temperature, model, tier, meter)
    return _ollama(system, user, temperature, model, tier, meter)
