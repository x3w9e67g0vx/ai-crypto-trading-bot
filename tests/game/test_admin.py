from app.game.admin import admin_stats, set_banned
from app.game.analytics import log_event
from app.game.config import DAY_MS, SeasonKind
from app.game.seasons import ensure_current_season, join_season
from app.game.trading import open_position
from tests.game.conftest import NOW, make_player


def test_admin_stats(db, quotes):
    old = make_player(db, telegram_id=1, nickname="old")
    new = make_player(db, telegram_id=2, nickname="new", created_at=NOW - 1000)
    make_player(db, nickname="LSTM", is_ai=True, ai_key="lstm")
    day_start = NOW - NOW % DAY_MS
    log_event(db, old, "start", day_start - DAY_MS)
    log_event(db, old, "return", NOW)
    log_event(db, new, "start", NOW - 1000)
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    portfolio = join_season(db, old, week, NOW)
    open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)

    stats = admin_stats(db, NOW)

    assert stats["players"] == 2
    assert stats["new_24h"] == 1
    assert stats["d1"] == (1, 1)
    assert stats["d7"] == (0, 0)
    assert stats["week_active"] == 1
    assert stats["trades_today"] == 1


def test_ban_by_nickname_case_insensitive(db):
    player = make_player(db, telegram_id=1, nickname="Alice")
    make_player(db, nickname="LSTM", is_ai=True, ai_key="lstm")

    assert set_banned(db, "alice", True) is player
    assert player.is_banned is True
    assert set_banned(db, "ALICE", False) is player and player.is_banned is False
    assert set_banned(db, "nobody", True) is None
    assert set_banned(db, "lstm", True) is None
