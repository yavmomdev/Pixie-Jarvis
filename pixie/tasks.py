"""Background task runner.

Every tool call becomes an asyncio task that runs the (blocking) tool in a
worker thread. The user gets an instant reply and a notification when done.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass

from .notify import notify
from .tools import TOOLS


@dataclass
class Job:
    id: int
    tool: str
    args: dict


class TaskRunner:
    def __init__(self, max_parallel: int = 4, assistant_name: str = "Pixie"):
        self._sem = asyncio.Semaphore(max_parallel)
        self._ids = itertools.count(1)
        self._running: set[asyncio.Task] = set()
        self.name = assistant_name

    def submit(self, tool: str, args: dict | None = None) -> Job:
        job = Job(next(self._ids), tool, args or {})
        task = asyncio.create_task(self._run(job))
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        return job

    async def _run(self, job: Job) -> None:
        t = TOOLS.get(job.tool)
        if t is None:
            notify(self.name, f"I don't know how to '{job.tool}' yet.")
            return
        async with self._sem:
            try:
                result = await asyncio.to_thread(t.fn, **job.args)
            except TypeError as e:  # the LLM sent bad arguments
                result = f"{job.tool}: wrong arguments ({e})"
            except Exception as e:
                result = f"{job.tool} failed: {e}"
        notify(self.name, str(result))

    @property
    def active(self) -> int:
        return len(self._running)

    async def wait_all(self) -> None:
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
