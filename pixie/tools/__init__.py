"""Tool registry.

Every skill is a plain Python function decorated with @tool. The decorator
registers it and builds the JSON schema the LLM uses for tool calling.
Adding a new skill = adding a new file in this folder with @tool functions.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., str]
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": self.required,
                },
            },
        }


class Copyable(str):
    """Return this from a tool when the result is text the user will want to copy
    (an email draft, a written text...). The popup then shows a Copy button."""


class Info(str):
    """Return this when the result is information the user asked for (a search answer,
    what's playing, a list...). The popup shows it solid and full-size, not as a small
    see-through status pill."""


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, params: dict | None = None, required: list[str] | None = None):
    def deco(fn: Callable[..., str]):
        TOOLS[name] = Tool(name, description, fn, params or {}, required or [])
        return fn

    return deco


def load_all() -> dict[str, Tool]:
    """Import every module in this package so their @tool functions register."""
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
    return TOOLS


def schemas() -> list[dict]:
    return [t.schema() for t in TOOLS.values()]
