"""Loads config.yaml (falls back to config.example.yaml) and merges it with defaults."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "assistant_name": "Pixie",
    "ollama": {
        "host": "http://localhost:11434",
        "model": "qwen2.5:7b",
    },
    "spotify": {
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:8888/callback",
        "liked_songs_limit": 100,
    },
    "search": {"max_results": 5},
    "apps": {},
    "notifications": True,
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    for name in ("config.yaml", "config.example.yaml"):
        path = ROOT / name
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return _merge(DEFAULTS, yaml.safe_load(f) or {})
    return copy.deepcopy(DEFAULTS)


CONFIG = load_config()
