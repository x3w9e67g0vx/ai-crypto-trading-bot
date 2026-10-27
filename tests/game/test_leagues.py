import pytest

from app.game.config import DAY_MS, SeasonKind
from app.game.leagues import apply_week_results, assign_group, compute_movements, movement_count
from app.game.models import LeagueGroup, LeagueMembership
from app.game.seasons import ensure_current_season, join_season
from tests.game.conftest import NOW, make_player

_ids = iter(range(1, 10_000))


def join(db, season, tier="silver", cash=10_000.0, trades=5, now=NOW, **kw):
    player = make_player(db, telegram_id=next(_ids), league_tier=tier, **kw)
    portfolio = join_season(db, player, season, now)
    portfolio.cash = cash
    portfolio.trades_count = trades
    return player, portfolio


@pytest.fixture
def week(db):
    return ensure_current_season(db, SeasonKind.WEEK, NOW)


def test_movement_count():
    assert movement_count(30, 30) == 5
    assert movement_count(31, 3) == 5
    assert movement_count(29, 10) == 2
    assert movement_count(12, 5) == 1
    assert movement_count(12, 4) == 0


def test_compute_movements():
    assert compute_movements([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 10) == ([1, 2], [9, 10])
    assert compute_movements([1, 2, 3], 10) == ([], [])


def test_full_group_top5_bottom5(db, week, quotes):
    players = [join(db, week, cash=10_000.0 + i)[0] for i in range(30)]
    apply_week_results(db, week, quotes, week.ends_at)
    tiers = [player.league_tier for player in players]
    assert tiers[-5:] == ["gold"] * 5
    assert tiers[:5] == ["bronze"] * 5
    assert set(tiers[5:25]) == {"silver"}


def test_small_group_no_movement(db, week, quotes):
    active = [join(db, week, cash=10_000.0 + i)[0] for i in range(4)]
    idle_member = join(db, week, trades=0)[0]
    absent = make_player(db, telegram_id=next(_ids), league_tier="gold")
    apply_week_results(db, week, quotes, week.ends_at)
    assert [player.league_tier for player in active] == ["silver"] * 4
    assert idle_member.league_tier == "bronze"
    assert absent.league_tier == "silver"


def test_unqualified_players_stay(db, week, quotes):
    for i in range(5):
        join(db, week, cash=10_000.0 + i)
    lucky = join(db, week, cash=50_000.0, trades=3)[0]
    apply_week_results(db, week, quotes, week.ends_at)
    assert lucky.league_tier == "silver"


def test_bronze_not_demoted_diamond_not_promoted(db, week, quotes):
    bronze = [join(db, week, tier="bronze", cash=10_000.0 + i)[0] for i in range(5)]
    diamond = [join(db, week, tier="diamond", cash=10_000.0 + i)[0] for i in range(5)]
    apply_week_results(db, week, quotes, week.ends_at)
    assert bronze[0].league_tier == "bronze"
    assert bronze[-1].league_tier == "silver"
    assert diamond[-1].league_tier == "diamond"
    assert diamond[0].league_tier == "platinum"


def test_ai_ghosts_take_no_league_slots(db, week, quotes):
    players = [join(db, week, cash=10_000.0 + i)[0] for i in range(5)]
    ai = make_player(db, nickname="LSTM", is_ai=True, ai_key="lstm")
    ai_portfolio = join_season(db, ai, week, NOW)
    ai_portfolio.cash, ai_portfolio.trades_count = 99_000.0, 50
    apply_week_results(db, week, quotes, week.ends_at)
    assert players[-1].league_tier == "gold"
    assert db.query(LeagueMembership).filter_by(portfolio_id=ai_portfolio.id).count() == 0


def test_assign_fills_group_then_creates_new(db, week):
    for _ in range(31):
        join(db, week, tier="bronze", now=week.starts_at + 60_000)
    groups = db.query(LeagueGroup).filter_by(season_id=week.id, tier="bronze").order_by(LeagueGroup.number).all()
    assert [group.number for group in groups] == [1, 2]
    sizes = [db.query(LeagueMembership).filter_by(group_id=group.id).count() for group in groups]
    assert sizes == [30, 1]


def test_midweek_join_goes_to_existing_group(db, week):
    for _ in range(30):
        join(db, week, tier="bronze", now=week.starts_at + 60_000)
    _, late = join(db, week, tier="bronze", now=week.starts_at + 3 * DAY_MS)
    membership = db.query(LeagueMembership).filter_by(portfolio_id=late.id).one()
    assert db.get(LeagueGroup, membership.group_id).number == 1
