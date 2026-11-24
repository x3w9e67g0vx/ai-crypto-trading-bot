import asyncio

from app.game.config import SeasonKind
from app.game.models import Notification, Portfolio
from app.game.seasons import ensure_current_season
from app.telegram.notifier import notify_once
from tests.telegram.conftest import texts


def test_notifier_sends_and_survives_send_error(harness, session_factory, quotes):
    for user_id, name in ((1, "one"), (2, "two")):
        harness.message("/rank", user_id=user_id, username=name)
    with session_factory() as db:
        week = ensure_current_season(db, SeasonKind.WEEK, harness.clock["now"])
        db.query(Portfolio).filter_by(season_id=week.id).update({"trades_count": 1})
        db.commit()
        at = week.ends_at - 30 * 60_000
    harness.session.fail_chats.add(1)
    harness.session.calls.clear()

    sent = asyncio.run(notify_once(harness.bot, session_factory, quotes, at))

    assert sent == 1
    delivered = texts(harness.session.calls)
    assert len(delivered) == 2 and all("/settings" in text for text in delivered)
    with session_factory() as db:
        assert db.query(Notification).count() == 2
    assert asyncio.run(notify_once(harness.bot, session_factory, quotes, at + 60_000)) == 0


def test_render_duel_result():
    from app.game.models import Player
    from app.game.notifications import Outgoing
    from app.telegram.notifier import render

    params = {"rival": "bob", "my_pct": 3.2, "rival_pct": -1.1, "score": [2, 1], "outcome": "win", "xp": 50}
    text = render(Outgoing(Player(nickname="a", language="ru"), "duel_result", params))
    assert "bob" in text and "+3.20%" in text and "2:1" in text and "+50 XP" in text


def test_notifier_retries_once_after_429(harness, session_factory, quotes, monkeypatch):
    from aiogram.exceptions import TelegramRetryAfter

    harness.message("/rank", user_id=1, username="one")
    with session_factory() as db:
        week = ensure_current_season(db, SeasonKind.WEEK, harness.clock["now"])
        db.query(Portfolio).filter_by(season_id=week.id).update({"trades_count": 1})
        db.commit()
        at = week.ends_at - 30 * 60_000
    real = harness.session.make_request
    flooded = []

    async def flood_once(bot, method, timeout=None):
        if not flooded:
            flooded.append(method)
            raise TelegramRetryAfter(method=method, message="429", retry_after=1)
        return await real(bot, method, timeout)

    monkeypatch.setattr(harness.session, "make_request", flood_once)
    harness.session.calls.clear()
    assert asyncio.run(notify_once(harness.bot, session_factory, quotes, at)) == 1
    assert len(texts(harness.session.calls)) == 1
