from app.game.config import SeasonKind
from app.game.models import Notification, Position
from app.game.notifications import collect_notifications
from app.game.seasons import ensure_current_season, join_season
from tests.game.conftest import NOW, make_player

HOUR = 60 * 60 * 1000


def _trader(db, season, telegram_id, cash, trades=5, **kw):
    player = make_player(db, telegram_id=telegram_id, nickname=f"p{telegram_id}", **kw)
    portfolio = join_season(db, player, season, NOW)
    portfolio.cash = cash
    portfolio.trades_count = trades
    db.flush()
    return player, portfolio


def _kinds(outgoing):
    return sorted((item.player.nickname, item.kind) for item in outgoing)


def _ai_position(db, season, opened_at, symbol="BTC/USDT"):
    ai = make_player(db, nickname=f"AI{opened_at}", is_ai=True, ai_key=f"ai{opened_at}")
    portfolio = join_season(db, ai, season, NOW)
    position = Position(
        portfolio_id=portfolio.id, symbol=symbol, side="long", qty=1, entry_price=100,
        reserved=100, opened_at=opened_at,
    )
    db.add(position)
    db.flush()
    return position


def test_first_check_only_records_rank(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 11_000)
    _trader(db, week, 2, 10_500)

    assert collect_notifications(db, quotes, NOW) == []


def test_overtaken_when_rank_drops(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 11_000)
    _, chaser = _trader(db, week, 2, 10_500)
    collect_notifications(db, quotes, NOW)

    chaser.cash = 12_000
    outgoing = collect_notifications(db, quotes, NOW + 60_000)

    assert _kinds(outgoing) == [("p1", "overtaken")]
    assert outgoing[0].params == {"old_rank": 1, "new_rank": 2}


def test_ai_open_only_for_pro(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 10_000, is_pro_until=NOW + HOUR)
    _trader(db, week, 2, 10_000)
    _ai_position(db, week, NOW - 60_000)

    outgoing = collect_notifications(db, quotes, NOW)

    assert _kinds(outgoing) == [("p1", "ai_open")]
    assert outgoing[0].params["symbol"] == "BTC/USDT"


def test_old_ai_positions_not_announced(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 10_000, is_pro_until=NOW + HOUR)
    _ai_position(db, week, NOW - HOUR)

    assert collect_notifications(db, quotes, NOW) == []


def test_season_end_hour_before_for_traders(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 10_000, trades=1)
    _trader(db, week, 2, 10_000, trades=0)

    assert collect_notifications(db, quotes, week.ends_at - 2 * HOUR) == []
    outgoing = collect_notifications(db, quotes, week.ends_at - HOUR // 2)

    assert ("p1", "season_end") in _kinds(outgoing)
    assert ("p2", "season_end") not in _kinds(outgoing)


def test_same_event_not_repeated(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 10_000, trades=1)
    at = week.ends_at - HOUR // 2

    assert len(collect_notifications(db, quotes, at)) == 1
    assert collect_notifications(db, quotes, at + 60_000) == []


def test_daily_cap(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    _trader(db, week, 1, 10_000, is_pro_until=NOW + HOUR)
    for minute in range(5):
        _ai_position(db, week, NOW - minute * 60_000)

    assert len(collect_notifications(db, quotes, NOW)) == 3
    assert collect_notifications(db, quotes, NOW + 60_000) == []
    assert db.query(Notification).count() == 3


def test_disabled_kind_skipped(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    player, _ = _trader(db, week, 1, 10_000, trades=1, is_pro_until=week.ends_at)
    player.notify_season_end = False
    player.notify_ai_open = False
    _ai_position(db, week, week.ends_at - HOUR // 2 - 60_000)

    assert collect_notifications(db, quotes, week.ends_at - HOUR // 2) == []


def test_banned_and_ai_skipped(db, quotes):
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    banned, _ = _trader(db, week, 1, 10_000, trades=1)
    banned.is_banned = True
    _trader(db, week, None, 10_000, trades=1, is_ai=True, ai_key="lstm")

    assert collect_notifications(db, quotes, week.ends_at - HOUR // 2) == []
