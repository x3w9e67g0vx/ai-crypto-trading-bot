"""In-app scheduler: `python -m app.scheduler` (replaces Airflow).

One loop ticks every second and runs each job once its interval has passed.
A failing job is logged and tried again at its next interval; the others keep running.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TICK_S = 1.0


@dataclass(frozen=True)
class Job:
    name: str
    interval_s: float
    run: Callable[[], Awaitable[None]]


class Scheduler:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = jobs
        self._last: dict[str, float] = {}

    async def tick(self, now_s: float) -> list[str]:
        ran = []
        for job in self.jobs:
            last = self._last.get(job.name)
            if last is not None and now_s - last < job.interval_s:
                continue
            self._last[job.name] = now_s
            ran.append(job.name)
            try:
                await job.run()
            except Exception:
                logger.exception("job %s failed", job.name)
        return ran

    async def run(self) -> None:
        while True:
            await self.tick(time.monotonic())
            await asyncio.sleep(TICK_S)


def db_job(session_factory, fn: Callable) -> Callable[[], Awaitable[None]]:
    """Run fn(db) in a worker thread with its own session; commit, or roll back and re-raise."""

    def work() -> None:
        with session_factory() as db:
            try:
                fn(db)
                db.commit()
            except Exception:
                db.rollback()
                raise

    async def run() -> None:
        await asyncio.to_thread(work)

    return run
