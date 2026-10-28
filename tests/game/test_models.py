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


def test_notification_unique_per_key(db):
    from app.game.models import Notification

    player = make_player(db, telegram_id=1)
    db.add(Notification(player_id=player.id, kind="season_end", key="7", created_at=NOW))
    db.flush()
    db.add(Notification(player_id=player.id, kind="season_end", key="7", created_at=NOW + 1))
    with pytest.raises(IntegrityError):
        db.flush()


def test_chat_league_member_unique(db):
    from app.game.models import ChatLeague, ChatLeagueMember

    player = make_player(db, telegram_id=1)
    league = ChatLeague(chat_id=-100, title="chat", created_at=NOW)
    db.add(league)
    db.flush()
    db.add(ChatLeagueMember(league_id=league.id, player_id=player.id, joined_at=NOW))
    db.flush()
    db.add(ChatLeagueMember(league_id=league.id, player_id=player.id, joined_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def test_new_player_has_notifications_enabled(db):
    player = make_player(db, telegram_id=1)
    assert (player.notify_overtaken, player.notify_ai_open, player.notify_season_end) == (True, True, True)
