import asyncio

import pytest

from app.game.jobs import AiJob
from app.game.models import Player
from app.game.quotes import QuoteBook
from app.scheduler import Job, Scheduler, build_jobs, db_job, parse_channel_id
from tests.api.conftest import session_factory  # noqa: F401  shared fixture


def recorder(log, name, fail=False):
    async def run():
        log.append(name)
        if fail:
            raise RuntimeError(name)

    return run


def test_tick_runs_due_jobs_only():
    log = []
    scheduler = Scheduler([Job("fast", 10, recorder(log, "fast")), Job("slow", 60, recorder(log, "slow"))])
    assert asyncio.run(scheduler.tick(1000.0)) == ["fast", "slow"]
    assert asyncio.run(scheduler.tick(1009.9)) == []
    assert asyncio.run(scheduler.tick(1010.0)) == ["fast"]
    assert asyncio.run(scheduler.tick(1060.0)) == ["fast", "slow"]
    assert log == ["fast", "slow", "fast", "fast", "slow"]


def test_failing_job_does_not_stop_others():
    log = []
    scheduler = Scheduler([Job("broken", 10, recorder(log, "broken", fail=True)), Job("ok", 10, recorder(log, "ok"))])
    assert asyncio.run(scheduler.tick(0.0)) == ["broken", "ok"]
    # The failed job waits for its next interval, it is not retried every tick.
    assert asyncio.run(scheduler.tick(5.0)) == []
    assert asyncio.run(scheduler.tick(10.0)) == ["broken", "ok"]
    assert log == ["broken", "ok", "broken", "ok"]


def test_db_job_commits_and_rolls_back(session_factory):
    def add(db):
        db.add(Player(nickname="kept", created_at=0))

    def add_and_fail(db):
        db.add(Player(nickname="lost", created_at=0))
        db.flush()
        raise RuntimeError("boom")

    asyncio.run(db_job(session_factory, add)())
    with pytest.raises(RuntimeError):
        asyncio.run(db_job(session_factory, add_and_fail)())
    with session_factory() as db:
        assert [p.nickname for p in db.query(Player).all()] == ["kept"]


def intervals(jobs):
    return [(job.name, job.interval_s) for job in jobs]


def test_build_jobs_without_bot(session_factory):
    jobs = build_jobs(session_factory, QuoteBook(), bot=None, channel_id=-100, bot_username="", ai_job=AiJob())
    assert intervals(jobs) == [("seasons", 30), ("stops", 15), ("snapshots", 300), ("ai", 10)]


def test_build_jobs_with_channel(session_factory):
    bot = object()
    assert [name for name, _ in intervals(
        build_jobs(session_factory, QuoteBook(), bot=bot, channel_id=None, bot_username="b", ai_job=AiJob())
    )] == ["seasons", "stops", "snapshots", "ai", "notify"]
    jobs = build_jobs(session_factory, QuoteBook(), bot=bot, channel_id=-100, bot_username="b", ai_job=AiJob())
    assert intervals(jobs) == [
        ("seasons", 30), ("stops", 15), ("snapshots", 300), ("ai", 10), ("notify", 60), ("channel", 60),
    ]


def test_parse_channel_id():
    assert parse_channel_id("") is None
    assert parse_channel_id("-1001234") == -1001234
    assert parse_channel_id("@veydranox") == "@veydranox"
