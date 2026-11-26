import pytest

from app.game.channel import due_posts
from app.game.config import DAY_MS, HOUR_MS, WEEKEND_KIND
from app.game.errors import SeasonClosed
from app.game.jobs import run_seasons
from app.game.models import Badge, Event, Season
from app.game.shop import equip, wardrobe
from app.game.weekend import (
    ensure_weekend,
    live_weekend,
    register,
    weekend_bounds,
    weekend_info,
    weekend_portfolio,
)
from tests.game.conftest import NOW, make_player

# NOW is Wednesday 2026-10-28 12:00 UTC.
SAT = NOW - 12 * HOUR_MS + 3 * DAY_MS
MON = SAT + 2 * DAY_MS


def test_bounds_saturday_to_monday():
    assert weekend_bounds(NOW) == (SAT, MON)
    assert weekend_bounds(SAT + HOUR_MS) == (SAT, MON)
    assert weekend_bounds(MON) == (SAT + 7 * DAY_MS, MON + 7 * DAY_MS)  # Monday: the coming one


def test_sign_up_early_trade_from_saturday(db):
    alice = make_player(db, nickname="alice")
    portfolio = register(db, alice, NOW)
    assert register(db, alice, NOW + 1).id == portfolio.id
    assert db.query(Event).filter_by(kind="weekend_join").count() == 1
    assert portfolio.season.kind == WEEKEND_KIND and portfolio.cash == 10_000
    assert weekend_info(db, alice, NOW)["joined"] is True

    assert live_weekend(db, NOW) is None and weekend_portfolio(db, alice, NOW) is None
    assert weekend_portfolio(db, alice, SAT).id == portfolio.id
    assert weekend_portfolio(db, make_player(db, nickname="bob"), SAT) is None


def test_banned_cannot_sign_up(db):
    with pytest.raises(SeasonClosed):
        register(db, make_player(db, nickname="x", is_banned=True), NOW)


def _finish(db, quotes, cash_by_player):
    for player, cash in cash_by_player.items():
        portfolio = register(db, player, NOW)
        portfolio.cash, portfolio.trades_count = cash, 5
    db.flush()
    run_seasons(db, quotes, MON)


def test_top3_get_pro_days_and_cup_frame(db, quotes):
    players = [make_player(db, nickname=f"p{i}", telegram_id=i) for i in range(5)]
    newbie = make_player(db, nickname="new", created_at=SAT)  # too young for prizes
    _finish(db, quotes, {players[0]: 13_000, newbie: 20_000, players[1]: 12_000,
                         players[2]: 11_000, players[3]: 10_500, players[4]: 9_000})

    assert db.query(Season).filter_by(kind=WEEKEND_KIND, starts_at=SAT).one().status == "finished"
    pro_days = [(p.is_pro_until or MON) - MON for p in players]
    assert pro_days == [7 * DAY_MS, 5 * DAY_MS, 3 * DAY_MS, 0, 0]
    assert newbie.is_pro_until is None
    cups = {b.player_id for b in db.query(Badge).filter_by(code="weekend_cup")}
    assert cups == {players[0].id, players[1].id, players[2].id}

    def cup(player):
        return next(item for item in wardrobe(db, player, MON) if item["code"] == "frame_cup")

    assert cup(players[0]) == {"code": "frame_cup", "slot": "frame", "stars": None, "prize": True, "available": True}
    assert cup(players[3])["available"] is False
    equip(db, players[0], "frame", "frame_cup", MON + 30 * DAY_MS)  # stays after Pro ends
    assert players[0].frame == "frame_cup"


def test_channel_announce_on_friday_and_results(db, quotes):
    season = ensure_weekend(db, NOW)
    register(db, make_player(db, nickname="alice"), NOW)
    assert not [p for p in due_posts(db, quotes, SAT - 15 * HOUR_MS, "bot") if p.kind == "weekend"]
    [post] = [p for p in due_posts(db, quotes, SAT - 13 * HOUR_MS, "bot") if p.kind == "weekend"]
    assert post.key == str(season.id) and "?start=weekend" in post.text and "Уже записались: 1" in post.text
    assert not [p for p in due_posts(db, quotes, SAT - 12 * HOUR_MS, "bot") if p.kind == "weekend"]

    players = [make_player(db, nickname=f"p{i}") for i in range(3)]
    _finish(db, quotes, {p: 11_000 + i for i, p in enumerate(players)})
    [result] = [p for p in due_posts(db, quotes, MON + HOUR_MS, "bot") if p.kind == "season"]
    assert "Выходные" in result.text and "Кубок выходных" in result.text and "/weekend" in result.text
