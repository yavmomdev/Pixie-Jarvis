"""Run Pixie:
    python -m pixie            -> popup UI (hold Right Alt to talk)
    python -m pixie --console  -> text-only console mode

In console mode, type a command and press Enter. Pixie answers instantly and
does the work in the background.
"""

from __future__ import annotations

import asyncio
import sys

from .brain import Brain
from .config import CONFIG
from .tasks import TaskRunner
from . import app_index
from .tools import TOOLS, load_all


async def main() -> None:
    load_all()
    app_index.warm_up()  # scan installed apps in the background
    name = CONFIG.get("assistant_name", "Pixie")
    brain = Brain()
    runner = TaskRunner(assistant_name=name)

    print(f"🧚 {name} is ready ({CONFIG['ollama']['model']} via Ollama). Tools: {', '.join(TOOLS)}")
    print("Type a command, or 'exit' to quit.\n")

    while True:
        try:
            text = (await asyncio.to_thread(input, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit", "bye"}:
            break

        try:
            decision = await asyncio.to_thread(brain.decide, text)
        except Exception as e:
            print(f"{name}> I can't reach Ollama ({e}). Is it running? Try: ollama serve")
            continue

        for tool_name, args in decision.calls:
            runner.submit(tool_name, args)
        print(f"{name}> {decision.reply or '…'}")

    if runner.active:
        print(f"Finishing {runner.active} background task(s)…")
        await runner.wait_all()
    print("Bye 👋")


if __name__ == "__main__":
    if sys.stdout is None:  # started with pythonw (no console) -> log to a file
        from .config import ROOT

        sys.stdout = sys.stderr = open(ROOT / "pixie.log", "w", encoding="utf-8", buffering=1)
    elif sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # emojis in the Windows console
    if "--console" in sys.argv:
        asyncio.run(main())
    else:
        try:
            from .ui.app import run
        except ImportError as e:
            print(f"UI not available ({e}). Run: pip install -r requirements.txt")
            print("Starting console mode instead.\n")
            asyncio.run(main())
        else:
            run()
