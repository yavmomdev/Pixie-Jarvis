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


def chat(messages: list[dict], tools: list[dict] | None = None):
    """Raw chat call. Returns the Ollama response object."""
    return client().chat(
        model=model(),
        messages=messages,
        tools=tools or None,
        options={"temperature": 0.2},
    )


def complete(prompt: str, system: str | None = None) -> str:
    """Simple one-shot text generation (used by tools like search and email)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages).message.content.strip()
