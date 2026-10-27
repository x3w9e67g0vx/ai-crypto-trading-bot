from app.game.ai_personas import ensure_ai_players
from app.game.ai_view import ai_positions_view, is_pro
from app.game.models import Position
from app.game.seasons import join_season
from tests.game.conftest import NOW, make_player, make_season

MINUTE = 60 * 1000


def ai_portfolio_with_history(db):
    """Old open, recently closed and freshly opened positions."""
    lstm = ensure_ai_players(db, NOW)["lstm"]
    portfolio = join_season(db, lstm, make_season(db), NOW)

    def add(symbol, opened_min_ago, closed_min_ago=None):
        position = Position(
            symbol=symbol,
            side="long",
            qty=1.0,
            entry_price=100.0,
            reserved=100.0,
            opened_at=NOW - opened_min_ago * MINUTE,
            closed_at=None if closed_min_ago is None else NOW - closed_min_ago * MINUTE,
        )
        portfolio.positions.append(position)

    add("BTC/USDT", opened_min_ago=180)
    add("ETH/USDT", opened_min_ago=120, closed_min_ago=20)
    add("SOL/USDT", opened_min_ago=20)
    add("BTC/USDT", opened_min_ago=300, closed_min_ago=200)
    db.flush()
    return portfolio


def symbols(positions):
    return sorted(position.symbol for position in positions)


def test_free_viewer_sees_state_one_hour_ago(db):
    portfolio = ai_portfolio_with_history(db)
    viewer = make_player(db, telegram_id=1)

    assert symbols(ai_positions_view(db, viewer, portfolio, NOW)) == ["BTC/USDT", "ETH/USDT"]


def test_pro_viewer_sees_live(db):
    portfolio = ai_portfolio_with_history(db)
    viewer = make_player(db, telegram_id=1, is_pro_until=NOW + MINUTE)

    assert is_pro(viewer, NOW)
    assert symbols(ai_positions_view(db, viewer, portfolio, NOW)) == ["BTC/USDT", "SOL/USDT"]


def test_expired_pro_is_free(db):
    portfolio = ai_portfolio_with_history(db)
    viewer = make_player(db, telegram_id=1, is_pro_until=NOW)

    assert not is_pro(viewer, NOW)
    assert symbols(ai_positions_view(db, viewer, portfolio, NOW)) == ["BTC/USDT", "ETH/USDT"]
