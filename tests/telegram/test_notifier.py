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
