"""Run Pixie:  python -m pixie

Type a command and press Enter. Pixie answers instantly and does the work in
the background - you can keep typing new commands while old ones run.
"""

from __future__ import annotations

import asyncio
import sys

from .brain import Brain
from .config import CONFIG
from .tasks import TaskRunner
from .tools import TOOLS, load_all


async def main() -> None:
    load_all()
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
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # emojis in the Windows console
    asyncio.run(main())
