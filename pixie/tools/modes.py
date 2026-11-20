"""Modes: a named list of tool calls, defined in modes/*.yaml.

Example (modes/game_mode.yaml):
    name: game mode
    triggers: ["activate game mode", "game mode on"]
    steps:
      - open_app: {name: discord}
      - play_liked_songs: {shuffle: true}
"""

from __future__ import annotations

import time

import yaml

from ..config import ROOT
from . import TOOLS, tool

MODES_DIR = ROOT / "modes"


def load_modes() -> dict[str, dict]:
    modes = {}
    for path in sorted(MODES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = str(data.get("name", path.stem.replace("_", " "))).lower()
        modes[name] = data
    return modes


def match_trigger(text: str) -> str | None:
    """Exact trigger phrases skip the LLM entirely -> instant."""
    t = text.lower().strip(" .!?")
    for name, mode in load_modes().items():
        if t in [s.lower() for s in mode.get("triggers", [])]:
            return name
    return None


@tool(
    "run_mode",
    "Activate a mode, a saved routine of several actions (e.g. 'game mode', 'study mode').",
    {"name": {"type": "string", "description": "Mode name, e.g. 'game mode'"}},
    ["name"],
)
def run_mode(name: str) -> str:
    modes = load_modes()
    key = name.lower().strip()
    if key not in modes:
        key = next((k for k in modes if key in k or k in key), "")
    if not key:
        return f"No mode called '{name}'. Available: {', '.join(modes) or 'none'}."

    results = []
    for step in modes[key].get("steps", []):
        if isinstance(step, dict):  # "- open_app: {name: discord}"
            tool_name, args = next(iter(step.items()))
        else:  # "- some_tool" (no arguments)
            tool_name, args = str(step), {}
        t = TOOLS.get(tool_name)
        if not t or tool_name == "run_mode":
            results.append(f"skipped unknown step '{tool_name}'")
            continue
        try:
            results.append(t.fn(**(args or {})))
        except Exception as e:
            results.append(f"{tool_name} failed: {e}")
        time.sleep(float(modes[key].get("delay", 1)))
    return f"{key.title()} activated: " + " | ".join(results)
