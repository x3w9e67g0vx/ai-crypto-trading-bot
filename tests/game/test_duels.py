import pytest

from app.game.channel import due_posts
from app.game.config import DAY_MS, NOTIFY_DAILY_CAP, XP_PER_DUEL_DRAW, XP_PER_DUEL_WIN
from app.game.duels import (
    accept_duel,
    cancel_duel,
    create_duel,
    current_duel,
    duel_portfolio,
    duel_view,
    parse_duel,
    score,
)
from app.game.errors import DuelBusy, DuelNotFound, DuelOwn
from app.game.jobs import run_seasons
from app.game.models import Badge, Notification, Season
from app.game.notifications import collect_notifications
from tests.game.conftest import NOW, make_player


def pair(db):
    alice = make_player(db, nickname="alice", telegram_id=1)
    bob = make_player(db, nickname="bob", telegram_id=2)
    return alice, bob


def started(db):
    alice, bob = pair(db)
    duel = accept_duel(db, create_duel(db, alice, NOW).id, bob, NOW)
    return alice, bob, duel


def finish(db, quotes, duel, alice_cash, bob_cash, trades=(1, 1)):
    for player, cash, n in ((duel.challenger, alice_cash, trades[0]), (duel.opponent, bob_cash, trades[1])):
        portfolio = duel_portfolio(db, player, NOW)
        portfolio.cash, portfolio.trades_count = cash, n
    db.flush()
    run_seasons(db, quotes, NOW + DAY_MS)
    return duel


def test_parse_duel():
    assert parse_duel("duel_7") == 7
    assert parse_duel("ref_7") is None and parse_duel(None) is None


def test_invite_is_reused_and_cancellable(db):
    alice, _ = pair(db)
    duel = create_duel(db, alice, NOW)
    assert create_duel(db, alice, NOW + 1).id == duel.id
    cancel_duel(db, alice, NOW)
    assert current_duel(db, alice, NOW) is None


def test_accept_starts_24h_duel_season(db):
    alice, bob, duel = started(db)
    assert duel.status == "active" and duel.opponent_id == bob.id
    assert duel.season.kind == "duel" and duel.season.ends_at - duel.season.starts_at == DAY_MS
    assert duel_portfolio(db, alice, NOW).cash == duel_portfolio(db, bob, NOW).cash == 10_000
    view = duel_view(db, bob, None, NOW)
    assert view["state"] == "active" and view["rival"] == "alice" and view["score"] == [0, 0]


def test_accept_rules(db):
    alice, bob = pair(db)
    duel = create_duel(db, alice, NOW)
    with pytest.raises(DuelOwn):
        accept_duel(db, duel.id, alice, NOW)
    with pytest.raises(DuelNotFound):
        accept_duel(db, duel.id, bob, NOW + DAY_MS)  # expired
    accept_duel(db, duel.id, bob, NOW)
    with pytest.raises(DuelNotFound):
        accept_duel(db, duel.id, make_player(db, nickname="carol"), NOW)  # already taken
    carol = make_player(db, nickname="carol2")
    with pytest.raises(DuelBusy):
        accept_duel(db, create_duel(db, carol, NOW).id, bob, NOW)
    with pytest.raises(DuelBusy):
        create_duel(db, alice, NOW)


def test_accepting_drops_own_invite(db):
    alice, bob = pair(db)
    create_duel(db, bob, NOW)
    accept_duel(db, create_duel(db, alice, NOW).id, bob, NOW)
    assert current_duel(db, bob, NOW).challenger_id == alice.id


def test_win_awards_xp_score_and_no_badges_or_channel(db, quotes):
    alice, bob, duel = started(db)
    finish(db, quotes, duel, 10_300, 9_900)
    assert duel.status == "finished" and duel.winner_id == alice.id
    assert alice.xp == XP_PER_DUEL_WIN and bob.xp == 0
    assert score(db, alice.id, bob.id) == (1, 0)
    assert db.query(Badge).count() == 0
    assert not [post for post in due_posts(db, quotes, NOW + DAY_MS, "bot") if post.kind in ("season", "ai_move")]
    view = duel_view(db, bob, quotes, NOW + DAY_MS)
    assert view["state"] == "finished" and view["outcome"] == "lose" and view["score"] == [0, 1]


def test_draw_and_no_xp_without_trades(db, quotes):
    alice, bob, duel = started(db)
    finish(db, quotes, duel, 10_000, 10_000.001, trades=(1, 0))
    assert duel.winner_id is None
    assert alice.xp == XP_PER_DUEL_DRAW and bob.xp == 0


def test_result_notified_to_both_past_the_cap(db, quotes):
    alice, bob, duel = started(db)
    for i in range(NOTIFY_DAILY_CAP):
        db.add(Notification(player_id=alice.id, kind="overtaken", key=str(i), created_at=NOW + DAY_MS))
    finish(db, quotes, duel, 9_000, 10_100)
    outgoing = collect_notifications(db, quotes, NOW + DAY_MS)
    results = {item.player.nickname: item.params for item in outgoing if item.kind == "duel_result"}
    assert results["alice"]["outcome"] == "lose" and results["bob"]["outcome"] == "win"
    assert results["bob"]["xp"] == XP_PER_DUEL_WIN
    assert not [i for i in collect_notifications(db, quotes, NOW + DAY_MS) if i.kind == "duel_result"]


def test_duel_season_not_auto_created(db, quotes):
    run_seasons(db, quotes, NOW)
    assert db.query(Season).filter_by(kind="duel").count() == 0
