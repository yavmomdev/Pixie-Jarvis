"""Thin wrapper around the local Ollama server."""

from __future__ import annotations

from functools import lru_cache

from .config import CONFIG


@lru_cache(maxsize=1)
def client():
    import ollama

    return ollama.Client(host=CONFIG["ollama"]["host"])


def model() -> str:
    return CONFIG["ollama"]["model"]


def _options() -> dict:
    cfg = CONFIG["ollama"]
    # Pixie's instructions + ~25 tool descriptions need more than Ollama's small default
    # context window; if it's too small the model silently forgets part of them.
    return {"temperature": 0.1, "num_ctx": int(cfg.get("num_ctx", 8192))}


def chat(messages: list[dict], tools: list[dict] | None = None):
    """Raw chat call. Returns the Ollama response object."""
    return client().chat(
        model=model(),
        messages=messages,
        tools=tools or None,
        options=_options(),
        keep_alive=CONFIG["ollama"].get("keep_alive", "2h"),  # stay loaded -> no reload delay
    )


def warm_up() -> None:
    """Load the model into (GPU) memory at startup, so the first command is fast."""
    try:
        client().chat(
            model=model(), messages=[{"role": "user", "content": "hi"}],
            options={**_options(), "num_predict": 1}, keep_alive=CONFIG["ollama"].get("keep_alive", "2h"),
        )
    except Exception as e:
        print(f"[llm] warm-up failed: {e}")


def complete(prompt: str, system: str | None = None) -> str:
    """Simple one-shot text generation (used by tools like search and email)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages).message.content.strip()
