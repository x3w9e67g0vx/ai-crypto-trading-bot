from app.game.ai_personas import ensure_ai_players
from app.game.models import Portfolio
from app.game.share import share_info
from tests.game.conftest import NOW, make_player, make_season


def _portfolio(db, player, season, cash, trades=5):
    portfolio = Portfolio(player_id=player.id, season_id=season.id, cash=cash, trades_count=trades, created_at=NOW)
    db.add(portfolio)
    db.flush()
    return portfolio


def test_share_info_beat_ai(db, quotes):
    season = make_season(db)
    mine = _portfolio(db, make_player(db, telegram_id=1, nickname="alice"), season, 11_200.0)
    _portfolio(db, make_player(db, telegram_id=2, nickname="bob"), season, 11_500.0)
    ais = ensure_ai_players(db, NOW)
    _portfolio(db, ais["lstm"], season, 10_400.0)
    _portfolio(db, ais["random_forest"], season, 10_800.0)

    info = share_info(db, mine, quotes, NOW)

    assert round(info.return_pct, 6) == 12.0
    assert info.rank == 2
    assert round(info.beat_ai_by, 6) == 4.0


def test_share_info_behind_ai(db, quotes):
    season = make_season(db)
    mine = _portfolio(db, make_player(db, telegram_id=1), season, 9_900.0, trades=1)
    _portfolio(db, ensure_ai_players(db, NOW)["lstm"], season, 10_100.0)

    info = share_info(db, mine, quotes, NOW)

    assert info.rank is None
    assert round(info.beat_ai_by, 6) == -2.0
