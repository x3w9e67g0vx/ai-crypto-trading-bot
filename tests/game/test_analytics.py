from app.game.analytics import log_event, retention
from app.game.config import DAY_MS
from app.game.models import Event
from tests.game.conftest import NOW, make_player

DAY_START = NOW - NOW % DAY_MS


def test_once_per_day(db):
    player = make_player(db, telegram_id=1)

    assert log_event(db, player, "return", NOW, once_per_day=True) is True
    assert log_event(db, player, "return", NOW + 60_000, once_per_day=True) is False
    assert log_event(db, player, "return", DAY_START + DAY_MS, once_per_day=True) is True
    assert log_event(db, player, "trade", NOW) is True
    assert log_event(db, player, "trade", NOW) is True
    assert db.query(Event).count() == 4


def test_retention_counts_event_on_day_n(db):
    stays, leaves, early = (make_player(db, telegram_id=i, nickname=f"p{i}") for i in (1, 2, 3))
    first = DAY_START - 7 * DAY_MS + 1000
    for player in (stays, leaves, early):
        log_event(db, player, "start", first)
    log_event(db, stays, "trade", first + 7 * DAY_MS)
    log_event(db, early, "trade", first + 6 * DAY_MS)

    assert retention(db, 7, NOW) == (1, 3)
    assert retention(db, 1, NOW) == (0, 3)


def test_retention_cohort_excludes_young_players(db):
    old, young = make_player(db, telegram_id=1, nickname="old"), make_player(db, telegram_id=2, nickname="young")
    log_event(db, old, "start", DAY_START - DAY_MS)
    log_event(db, young, "start", NOW)
    log_event(db, old, "return", NOW)

    assert retention(db, 1, NOW) == (1, 1)
    assert retention(db, 7, NOW) == (0, 0)
