import pytest
from sqlalchemy.exc import IntegrityError

from app.game.models import Player, Portfolio
from tests.game.conftest import NOW, make_player, make_season


def test_portfolio_is_unique_per_player_and_season(db):
    player = make_player(db, telegram_id=1)
    season = make_season(db)
    db.add(Portfolio(player_id=player.id, season_id=season.id, cash=10_000.0, created_at=NOW))
    db.flush()
    db.add(Portfolio(player_id=player.id, season_id=season.id, cash=10_000.0, created_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def test_ai_player_has_no_telegram_id(db):
    db.add(Player(nickname="LSTM", is_ai=True, ai_key="lstm", telegram_id=None, created_at=NOW))
    db.add(Player(nickname="RF", is_ai=True, ai_key="random_forest", telegram_id=None, created_at=NOW))
    db.flush()
    assert db.query(Player).filter_by(is_ai=True).count() == 2
    assert db.query(Player).first().league_tier == "bronze"
