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

from aiogram import Bot

from app.core.config import settings
from app.game.jobs import AiJob, run_seasons, run_snapshots, run_stops
from app.game.quote_store import run_quote_sync
from app.game.quotes import QuoteBook
from app.telegram.bot import make_bot
from app.telegram.channel import publish_once
from app.telegram.notifier import notify_once

logger = logging.getLogger(__name__)

TICK_S = 1.0


@dataclass(frozen=True)
class Job:
    name: str
    interval_s: float
    run: Callable[[], Awaitable[object]]  # a truthy result is logged


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
                result = await job.run()
            except Exception:
                logger.exception("job %s failed", job.name)
            else:
                if result:
                    logger.info("job %s: %s", job.name, result)
        return ran

    async def run(self) -> None:
        while True:
            await self.tick(time.monotonic())
            await asyncio.sleep(TICK_S)


def db_job(session_factory, fn: Callable) -> Callable[[], Awaitable[object]]:
    """Run fn(db) in a worker thread with its own session; commit, or roll back and re-raise."""

    def work():
        with session_factory() as db:
            try:
                result = fn(db)
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    async def run():
        return await asyncio.to_thread(work)

    return run


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_channel_id(raw: str) -> int | str | None:
    """CHANNEL_ID is a numeric chat id or an @username; empty means no channel."""
    raw = raw.strip()
    if not raw:
        return None
    return int(raw) if raw.lstrip("-").isdigit() else raw


def build_jobs(
    session_factory,
    quotes: QuoteBook,
    *,
    bot: Bot | None,
    channel_id: int | str | None,
    bot_username: str,
    ai_job: AiJob,
) -> list[Job]:
    jobs = [
        Job("seasons", 30, db_job(session_factory, lambda db: run_seasons(db, quotes, now_ms()))),
        Job("stops", 15, db_job(session_factory, lambda db: run_stops(db, quotes, now_ms()))),
        Job("snapshots", 300, db_job(session_factory, lambda db: run_snapshots(db, quotes, now_ms()))),
        Job("ai", 10, db_job(session_factory, lambda db: ai_job.run(db, quotes, now_ms()))),
    ]
    if bot is not None:
        jobs.append(Job("notify", 60, lambda: notify_once(bot, session_factory, quotes, now_ms())))
        if channel_id is not None:
            jobs.append(
                Job("channel", 60, lambda: publish_once(bot, session_factory, quotes, channel_id, bot_username, now_ms()))
            )
    return jobs


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from app.core.db.session import SessionLocal

    quotes = QuoteBook()
    # Notifications and channel posts only send messages, so no polling and no getMe here.
    bot = make_bot() if settings.TELEGRAM_BOT_TOKEN else None
    jobs = build_jobs(
        SessionLocal,
        quotes,
        bot=bot,
        channel_id=parse_channel_id(settings.CHANNEL_ID),
        bot_username=settings.BOT_USERNAME,
        ai_job=AiJob(),
    )
    logger.info("scheduler jobs: %s", ", ".join(job.name for job in jobs))
    sync = asyncio.create_task(run_quote_sync(SessionLocal, quotes, publish=False))
    try:
        await Scheduler(jobs).run()
    finally:
        sync.cancel()
        if bot is not None:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
