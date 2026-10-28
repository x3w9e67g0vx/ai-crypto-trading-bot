import pytest

from app.game.chat_leagues import chat_league_table, ensure_chat_league, join_chat_league
from app.game.config import SeasonKind
from app.game.errors import SeasonClosed
from app.game.models import ChatLeague, ChatLeagueMember, Portfolio
from app.game.seasons import ensure_current_season, join_season
from tests.game.conftest import NOW, make_player


def test_ensure_chat_league_once_per_chat(db):
    first = ensure_chat_league(db, -100, "Friends", NOW)
    again = ensure_chat_league(db, -100, "Friends renamed", NOW + 1)

    assert first.id == again.id
    assert again.title == "Friends renamed"
    assert db.query(ChatLeague).count() == 1


def test_join_enters_week_season(db):
    league = ensure_chat_league(db, -100, "Friends", NOW)
    player = make_player(db, telegram_id=1)

    assert join_chat_league(db, league, player, NOW) is True

    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    assert db.query(Portfolio).filter_by(player_id=player.id, season_id=week.id).count() == 1


def test_join_is_idempotent(db):
    league = ensure_chat_league(db, -100, "Friends", NOW)
    player = make_player(db, telegram_id=1)

    assert join_chat_league(db, league, player, NOW) is True
    assert join_chat_league(db, league, player, NOW + 1) is False
    assert db.query(ChatLeagueMember).count() == 1


def test_player_in_several_leagues(db):
    player = make_player(db, telegram_id=1)
    for chat_id in (-100, -200):
        assert join_chat_league(db, ensure_chat_league(db, chat_id, "chat", NOW), player, NOW) is True
    assert db.query(ChatLeagueMember).filter_by(player_id=player.id).count() == 2


def test_banned_cannot_join(db):
    league = ensure_chat_league(db, -100, "Friends", NOW)
    player = make_player(db, telegram_id=1)
    join_season(db, player, ensure_current_season(db, SeasonKind.WEEK, NOW), NOW)
    player.is_banned = True

    with pytest.raises(SeasonClosed):
        join_chat_league(db, league, player, NOW)
    assert db.query(ChatLeagueMember).count() == 0


def test_table_has_members_and_ai_only(db, quotes):
    league = ensure_chat_league(db, -100, "Friends", NOW)
    member = make_player(db, telegram_id=1, nickname="member")
    outsider = make_player(db, telegram_id=2, nickname="outsider")
    ai = make_player(db, nickname="LSTM", is_ai=True, ai_key="lstm")
    week = ensure_current_season(db, SeasonKind.WEEK, NOW)
    for player in (outsider, ai):
        join_season(db, player, week, NOW)
    join_chat_league(db, league, member, NOW)

    rows = chat_league_table(db, league, quotes, NOW)

    assert sorted(row.nickname for row in rows) == ["LSTM", "member"]
