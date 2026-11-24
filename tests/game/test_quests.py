from app.game.config import STARTING_BALANCE
from app.game.models import Event, Position, QuestClaim
from app.game.quests import QUESTS, claim_quests
from app.game.seasons import current_portfolio
from tests.game.conftest import NOW, make_player


def add_closed(db, portfolio, n, *, stop=None, reason="manual", pnl=1.0):
    for _ in range(n):
        db.add(Position(portfolio_id=portfolio.id, symbol="BTC/USDT", side="long", qty=1, entry_price=100,
                        reserved=100, stop_loss=stop, opened_at=NOW, closed_at=NOW, exit_price=100,
                        pnl=pnl, close_reason=reason))
    db.flush()


def by_code(rows):
    return {row["code"]: row for row in rows}


def setup(db):
    player = make_player(db)
    return player, current_portfolio(db, player, "week", NOW)


def test_fresh_portfolio_has_nothing_done(db):
    player, portfolio = setup(db)
    rows, xp = claim_quests(db, portfolio, NOW)
    assert xp == 0 and player.xp == 0
    assert [row["code"] for row in rows] == [quest.code for quest in QUESTS]
    assert not any(row["done"] or row["failed"] for row in rows)


def test_stops_and_take_profit_award_once(db):
    player, portfolio = setup(db)
    add_closed(db, portfolio, 4, stop=90)
    add_closed(db, portfolio, 1, stop=90, reason="take_profit")
    add_closed(db, portfolio, 1)  # open position without a stop does not count
    rows, xp = claim_quests(db, portfolio, NOW)
    quests = by_code(rows)
    assert quests["stops"]["progress"] == 5 and quests["stops"]["done"]
    assert quests["take_profit"]["done"]
    assert quests["discipline"]["done"]  # 6 trades, no big loss
    assert xp == player.xp == 30 + 30 + 50
    assert db.query(Event).filter_by(kind="quest_done").count() == 3

    assert claim_quests(db, portfolio, NOW)[1] == 0
    assert player.xp == 110
    assert db.query(QuestClaim).count() == 3


def test_big_loss_fails_discipline(db):
    _, portfolio = setup(db)
    add_closed(db, portfolio, 5)
    add_closed(db, portfolio, 1, pnl=-STARTING_BALANCE * 0.021)
    quests = by_code(claim_quests(db, portfolio, NOW)[0])
    assert quests["discipline"]["failed"] and not quests["discipline"]["done"]
    assert quests["discipline"]["progress"] == 5


def test_progress_capped_at_target(db):
    _, portfolio = setup(db)
    add_closed(db, portfolio, 7, stop=90)
    assert by_code(claim_quests(db, portfolio, NOW)[0])["stops"]["progress"] == 5
