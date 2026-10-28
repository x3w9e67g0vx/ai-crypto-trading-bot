import pytest

from app.game.ai_personas import ensure_ai_players
from app.game.channel import ai_move_post, evening_post, lesson_post, morning_post, season_post
from app.game.config import DAY_MS, SeasonKind
from app.game.lessons import get_lesson, get_lessons
from app.game.models import AiDecision, Badge, Portfolio, Position
from app.game.quotes import Quote
from app.game.trading import close_position, open_position
from app.i18n.strings import t
from tests.game.conftest import NOW, make_player, make_season
from tests.game.test_insights import add_candles

BOT = "veydranox_bot"
PNG = b"\x89PNG\r\n\x1a\n"
MINUTE = 60 * 1000


def decide(db, ai, symbol, probability_up, view, created_at):
    db.add(AiDecision(player_id=ai.id, symbol=symbol, candle_ts=created_at, probability_up=probability_up,
                      view=view, created_at=created_at))
    db.flush()


def join(db, player, season, *, cash=10_000.0, trades=5):
    portfolio = Portfolio(player_id=player.id, season_id=season.id, cash=cash, trades_count=trades, created_at=NOW)
    db.add(portfolio)
    db.flush()
    return portfolio


def closed(db, portfolio, *, symbol="BTC/USDT", side="long", pnl=10.0, reserved=1000.0,
           opened_at=NOW - 3 * 60 * MINUTE, closed_at=NOW - 60 * MINUTE, reason="manual"):
    position = Position(portfolio_id=portfolio.id, symbol=symbol, side=side, qty=10.0, entry_price=100.0,
                        reserved=reserved, opened_at=opened_at, closed_at=closed_at, exit_price=101.0,
                        pnl=pnl, close_reason=reason)
    db.add(position)
    db.flush()
    return position


def test_morning_post_lists_pairs_and_ai(db):
    add_candles(db, symbol="BTC/USDT")
    add_candles(db, symbol="ETH/USDT", rising=False)
    ais = ensure_ai_players(db, NOW)
    decide(db, ais["lstm"], "BTC/USDT", 0.62, "bullish", NOW - 90 * MINUTE)

    post = morning_post(db, NOW, BOT)

    assert (post.kind, post.key) == ("morning", "2026-10-28")
    assert "BTC/USDT" in post.text and "ETH/USDT" in post.text and "SOL/USDT" not in post.text
    assert "LSTM" in post.text and "62%" in post.text


def test_morning_hides_fresh_ai_opinions(db):
    add_candles(db, symbol="BTC/USDT")
    ais = ensure_ai_players(db, NOW)
    decide(db, ais["lstm"], "BTC/USDT", 0.40, "bearish", NOW - 80 * MINUTE)
    decide(db, ais["lstm"], "BTC/USDT", 0.91, "bullish", NOW - 10 * MINUTE)

    text = morning_post(db, NOW, BOT).text

    assert "40%" in text and "91%" not in text


def test_lesson_post_picks_rsi_lesson(db):
    add_candles(db, symbol="BTC/USDT", rising=True)  # RSI > 70

    post = lesson_post(db, NOW, BOT)

    assert (post.kind, post.key) == ("lesson", "2026-10-28")
    assert get_lesson("ru", "07").title in post.text
    assert post.image.startswith(PNG)


def test_lesson_post_rotates(db):
    lessons = get_lessons("ru")
    for day in range(2):
        now = NOW + day * DAY_MS
        expected = lessons[(now // DAY_MS) % len(lessons)]
        assert expected.title in lesson_post(db, now, BOT).text


def test_lesson_post_without_candles(db):
    post = lesson_post(db, NOW, BOT)
    assert post is not None and post.image is None


def test_evening_post_top_and_trade_of_day(db, quotes):
    sprint = make_season(db, SeasonKind.SPRINT)
    alice = make_player(db, telegram_id=1, nickname="alice")
    bob = make_player(db, telegram_id=2, nickname="bob")
    ais = ensure_ai_players(db, NOW)
    alice_portfolio = join(db, alice, sprint, trades=4)
    join(db, bob, sprint, cash=10_050.0)
    join(db, ais["lstm"], sprint, cash=10_200.0)

    position = open_position(db, alice_portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW - 1000)
    quotes.update(Quote("BTC/USDT", bid=110.0, ask=111.0, ts=NOW))
    close_position(db, position, quotes, NOW)

    post = evening_post(db, quotes, NOW + 1000, BOT)

    assert (post.kind, post.key) == ("evening", "2026-10-28")
    assert "1. alice" in post.text and "2. bob" in post.text
    assert "LSTM" in post.text and "+2.00%" in post.text
    assert "alice" in post.text.split(t("channel.evening.trade_title", lang="ru"))[1]


def test_evening_skips_banned_and_ai(db, quotes):
    sprint = make_season(db, SeasonKind.SPRINT)
    alice = make_player(db, telegram_id=1, nickname="alice")
    villain = make_player(db, telegram_id=2, nickname="villain", is_banned=True)
    ais = ensure_ai_players(db, NOW)
    join(db, alice, sprint)
    alice_trade = closed(db, join(db, alice, make_season(db)), pnl=10.0, closed_at=NOW)
    closed(db, join(db, villain, sprint, cash=20_000.0), pnl=900.0, closed_at=NOW)
    closed(db, join(db, ais["lstm"], sprint), pnl=800.0, closed_at=NOW)
    db.add(_fill(alice_trade))
    db.flush()

    text = evening_post(db, quotes, NOW + 1000, BOT).text

    assert "villain" not in text
    trade = text.split(t("channel.evening.trade_title", lang="ru"))[1]
    assert "alice" in trade and "LSTM" not in trade


def _fill(position):
    from app.game.models import Fill

    return Fill(portfolio_id=position.portfolio_id, position_id=position.id, symbol=position.symbol, side="sell",
                qty=position.qty, price=position.exit_price, fee=0.1, is_user=True, created_at=position.closed_at)


def test_season_post_results_and_badges(db, quotes):
    week = make_season(db)
    week.status = "finished"
    alice = make_player(db, telegram_id=1, nickname="alice")
    bob = make_player(db, telegram_id=2, nickname="bob")
    rookie = make_player(db, telegram_id=3, nickname="rookie")
    ais = ensure_ai_players(db, NOW)
    join(db, alice, week, cash=11_000.0)
    join(db, bob, week, cash=9_000.0)
    join(db, rookie, week, cash=12_000.0, trades=2)
    join(db, ais["lstm"], week, cash=10_500.0)
    db.add(Badge(player_id=alice.id, code="sniper", season_id=week.id, created_at=NOW))
    db.flush()

    post = season_post(db, week, quotes, week.ends_at + 1000, BOT)

    assert (post.kind, post.key) == ("season", str(week.id))
    assert post.text.index("1. alice") < post.text.index("2. bob")
    assert "rookie" not in post.text
    assert "LSTM" in post.text and "+5.00%" in post.text
    assert t("channel.season.beat_ai", lang="ru", beat=1, total=2) in post.text
    assert "alice" in post.text.split(t("channel.badge.sniper", lang="ru"))[1]


def test_ai_move_post_best_trade_with_chart(db):
    week = make_season(db)
    week.status = "finished"
    ais = ensure_ai_players(db, NOW)
    portfolio = join(db, ais["random_forest"], week)
    add_candles(db, symbol="ETH/USDT", end_ms=NOW)
    closed(db, portfolio, symbol="BTC/USDT", pnl=-30.0)
    closed(db, portfolio, symbol="ETH/USDT", side="short", pnl=55.0, reserved=1100.0, reason="take_profit")

    post = ai_move_post(db, week, week.ends_at + 1000, BOT)

    assert (post.kind, post.key) == ("ai_move", str(week.id))
    assert "Random Forest" in post.text and "ETH/USDT" in post.text and "+5.00%" in post.text
    assert post.image.startswith(PNG)


def test_posts_skip_without_data(db, quotes):
    assert morning_post(db, NOW, BOT) is None
    assert evening_post(db, quotes, NOW, BOT) is None

    week = make_season(db)
    week.status = "finished"
    assert season_post(db, week, quotes, NOW, BOT) is None
    assert ai_move_post(db, week, NOW, BOT) is None

    sprint = make_season(db, SeasonKind.SPRINT)
    sprint.status = "finished"
    ais = ensure_ai_players(db, NOW)
    closed(db, join(db, ais["lstm"], sprint), pnl=5.0)
    assert ai_move_post(db, sprint, NOW, BOT) is None


@pytest.mark.parametrize("build", [lambda db: lesson_post(db, NOW, BOT)])
def test_posts_end_with_disclaimer_and_link(db, build):
    text = build(db).text
    assert t("disclaimer", lang="ru") in text
    assert text.rstrip().endswith(f"https://t.me/{BOT}")


DAY_START = NOW - NOW % DAY_MS
HOUR = 60 * MINUTE


def kinds(posts):
    return [(post.kind, post.key) for post in posts]


def test_due_posts_slots(db, quotes):
    from app.game.channel import due_posts

    add_candles(db, symbol="BTC/USDT", end_ms=DAY_START + 6 * HOUR)
    assert kinds(due_posts(db, quotes, DAY_START + 6 * HOUR + MINUTE, BOT)) == [("morning", "2026-10-28")]
    assert kinds(due_posts(db, quotes, DAY_START + 10 * HOUR + MINUTE, BOT)) == [("lesson", "2026-10-28")]
    # Nobody traded: the evening post waits for data inside its window.
    assert due_posts(db, quotes, DAY_START + 18 * HOUR + MINUTE, BOT) == []


def test_due_posts_once(db, quotes):
    from app.game.channel import due_posts
    from app.game.models import ChannelPost

    at = DAY_START + 10 * HOUR
    assert kinds(due_posts(db, quotes, at, BOT)) == [("lesson", "2026-10-28")]
    assert due_posts(db, quotes, at + MINUTE, BOT) == []
    assert db.query(ChannelPost).count() == 1


def test_slot_post_expires(db, quotes):
    from app.game.channel import due_posts

    add_candles(db, symbol="BTC/USDT", end_ms=DAY_START + 8 * HOUR)
    assert due_posts(db, quotes, DAY_START + 8 * HOUR + MINUTE, BOT) == []
    assert due_posts(db, quotes, DAY_START + 12 * HOUR, BOT) == []


def test_season_posts_after_finish_only(db, quotes):
    from app.game.channel import due_posts

    week = make_season(db, at_ms=NOW - 7 * DAY_MS)
    alice = make_player(db, telegram_id=1, nickname="alice")
    ais = ensure_ai_players(db, NOW)
    join(db, alice, week, cash=10_100.0)
    closed(db, join(db, ais["lstm"], week), pnl=5.0)
    quiet = week.ends_at + 3 * HOUR  # 03:00 UTC, no daily slot

    assert due_posts(db, quotes, quiet, BOT) == []  # still active
    week.status = "voided"
    assert due_posts(db, quotes, quiet, BOT) == []
    week.status = "finished"
    assert due_posts(db, quotes, week.ends_at + 3 * DAY_MS, BOT) == []  # too late
    assert kinds(due_posts(db, quotes, quiet, BOT)) == [("season", str(week.id)), ("ai_move", str(week.id))]
