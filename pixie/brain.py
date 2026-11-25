"""The brain: turns what you said into tool calls using the local LLM (Ollama)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from . import llm
from .config import CONFIG
from .tools import TOOLS, schemas
from .tools.modes import match_trigger

SYSTEM = """You are {name}, a fast personal desktop assistant on the user's Windows PC.
Rules:
- When the user wants something DONE, call the matching tool(s) right away - never ask
  "should I?". Several tools at once are fine (e.g. two apps = two open_app calls).
- Everything runs in the background. Pass show=true only if the user clearly wants to SEE it.
- Understand intent: "dc" = Discord, "code" = VS Code, "the browser" = their browser.
  Pass short names, not whole sentences.
- Music: "liked songs"/"put on music" -> play_liked_songs. A song/album/artist/playlist ->
  spotify_play (right kind). It opens Spotify itself, so don't also call open_app.
  YouTube only when the user says YouTube or it's a video (youtube_play; show=true to watch).
- Pause/skip: Spotify -> spotify_control, Pixie's YouTube audio -> youtube_control,
  "the music" in general -> media_control.
- Shutdown/restart only when clearly asked.
- Writing requests (a message, a text, a post) that aren't emails: just write the text as
  your reply. Emails -> draft_email.
- Chat or simple questions: answer in 1-2 short sentences, no tools.
- Reply in the user's language."""

# ---------------------------------------------------------------- fast path
# Simple, unambiguous commands run instantly without asking the LLM.
_FILLER = re.compile(r"^(hey |ok |okay )?(pixie|jarvis)[,!.]?\s*|\s*(please|pls|thanks|thank you)[.!]*$")
_FAST: list[tuple[re.Pattern, Callable[[re.Match], tuple[str, dict] | None]]] = [
    (re.compile(r"(pause|stop)( the)?( music| song| it| video)?"), lambda m: ("media_control", {"action": "play_pause"})),
    (re.compile(r"(resume|continue|unpause)( the)?( music| song| it)?"), lambda m: ("media_control", {"action": "play_pause"})),
    (re.compile(r"(next|skip)( song| track| one| this( song)?)?"), lambda m: ("media_control", {"action": "next"})),
    (re.compile(r"(previous|go back|last)( song| track| one)?"), lambda m: ("media_control", {"action": "previous"})),
    (re.compile(r"(set )?(the )?volume (to |at )?(\d{1,3})( ?%| percent)?"),
     lambda m: ("set_volume", {"action": "set", "level": int(m[4])})),
    (re.compile(r"(volume up|louder|turn (it|the volume) up)"), lambda m: ("set_volume", {"action": "up"})),
    (re.compile(r"(volume down|quieter|turn (it|the volume) down)"), lambda m: ("set_volume", {"action": "down"})),
    (re.compile(r"mute( the)?( sound| pc| computer)?"), lambda m: ("set_volume", {"action": "mute"})),
    (re.compile(r"unmute( the)?( sound| pc| computer)?"), lambda m: ("set_volume", {"action": "unmute"})),
    (re.compile(r"lock( my| the)?( pc| computer| laptop| screen)?"), lambda m: ("power", {"action": "lock"})),
    (re.compile(r"(take a )?screenshot"), lambda m: ("screenshot", {})),
    (re.compile(r"(play|put on|start) (my )?liked songs"), lambda m: ("play_liked_songs", {"shuffle": True})),
    (re.compile(r"what('s| is)( this| the)? (playing|song)( now| right now)?"), lambda m: _now_playing()),
    (re.compile(r"(open|launch|start) ([\w .+'-]{2,40})"), lambda m: _open_if_sure(m[2])),
]


def _now_playing() -> tuple[str, dict]:
    from .player import PLAYER

    if PLAYER.playing:
        return ("youtube_control", {"action": "now_playing"})
    return ("spotify_now_playing", {})


def _open_if_sure(name: str) -> tuple[str, dict] | None:
    """'open discord' -> instant, but only when the app name is an obvious match."""
    from .app_index import INDEX

    if " and " in name or "," in name:
        return None  # several things -> let the LLM split it
    best = INDEX.candidates(name, n=1)
    if best and best[0][0] >= 0.9:
        return ("open_app", {"name": name})
    return None


def fast_path(text: str) -> tuple[str, dict] | None:
    t = _FILLER.sub("", text.lower().strip()).strip(" .!?")
    for pattern, make in _FAST:
        m = pattern.fullmatch(t)
        if m:
            call = make(m)
            if call and call[0] in TOOLS:
                return call
    return None


@dataclass
class Decision:
    reply: str = ""
    calls: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def copyable(self) -> bool:
        """Pixie wrote a real text for you (not just 'On it') -> show a Copy button."""
        return not self.calls and (len(self.reply) >= 120 or self.reply.count("\n") >= 2)


class Brain:
    def __init__(self) -> None:
        self.name = CONFIG.get("assistant_name", "Pixie")
        self.history: list[dict] = []  # short chat memory for follow-ups

    def decide(self, text: str) -> Decision:
        # 1. instant paths: mode triggers and simple commands skip the LLM
        mode = match_trigger(text)
        if mode:
            return Decision(f"Activating {mode} 🚀", [("run_mode", {"name": mode})])
        quick = fast_path(text)
        if quick:
            return Decision("On it 👍", [quick])

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
