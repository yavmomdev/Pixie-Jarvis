"""The brain: turns what you said into tool calls using the local LLM (Ollama)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import llm
from .config import CONFIG
from .tools import TOOLS, schemas
from .tools.modes import match_trigger

SYSTEM = """You are {name}, a fast personal desktop assistant running on the user's Windows PC.
- When the user asks you to DO something (open an app, play music, search, write an email,
  activate a mode), ALWAYS call the matching tool(s). You may call several tools at once.
- To open several apps, call open_app once for EACH app ("open spotify and discord" = 2 calls).
- Understand what they mean: "music"/"songs" -> Spotify, "dc" -> Discord, "the browser" -> their
  browser, "code" -> VS Code. Pass the app name, not the whole sentence.
- "Play my liked songs" / "put on music" -> play_liked_songs (it opens Spotify by itself).
- Everything runs in the background, so never ask "should I do it?" - just call the tool.
- If the user is only chatting or asks something you can answer yourself, reply in 1-2 short
  sentences without tools.
- Reply in the same language the user used."""


@dataclass
class Decision:
    reply: str = ""
    calls: list[tuple[str, dict]] = field(default_factory=list)


class Brain:
    def __init__(self) -> None:
        self.name = CONFIG.get("assistant_name", "Pixie")
        self.history: list[dict] = []  # short chat memory for follow-ups

    def decide(self, text: str) -> Decision:
        # 1. instant path: exact mode triggers ("activate game mode") skip the LLM
        mode = match_trigger(text)
        if mode:
            return Decision(f"Activating {mode} 🚀", [("run_mode", {"name": mode})])

        # 2. ask the LLM which tools to use
        messages = [{"role": "system", "content": SYSTEM.format(name=self.name)}]
        messages += self.history[-6:]
        messages.append({"role": "user", "content": text})
        msg = llm.chat(messages, tools=schemas()).message

        calls: list[tuple[str, dict]] = []
        for tc in msg.tool_calls or []:
            args = tc.function.arguments or {}
            if isinstance(args, str):  # some models return a JSON string
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if tc.function.name in TOOLS:
                calls.append((tc.function.name, dict(args)))

        reply = (msg.content or "").strip()
        if calls and not reply:
            reply = "On it 👍"

        self.history += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply or ", ".join(n for n, _ in calls)},
        ]
        return Decision(reply, calls)
