import asyncio

import pytest

from app.game.models import Player
from app.scheduler import Job, Scheduler, db_job
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
